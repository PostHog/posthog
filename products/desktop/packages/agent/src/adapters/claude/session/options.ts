import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type {
  CanUseTool,
  McpServerConfig,
  Options,
  OutputFormat,
  SpawnedProcess,
  SpawnOptions,
} from "@anthropic-ai/claude-agent-sdk";
import type { FileEnrichmentDeps } from "../../../enrichment/file-enricher";
import { IS_ROOT } from "../../../utils/common";
import { buildGatewayPropertyHeaders } from "../../../utils/gateway";
import type { Logger } from "../../../utils/logger";
import type { TaskState } from "../conversion/task-state";
import {
  createPostToolUseHook,
  createPreToolUseHook,
  createReadEnrichmentHook,
  createReadImageGuardHook,
  createSignedCommitGuardHook,
  createSubagentRewriteHook,
  createTaskHook,
  type EnrichedReadCache,
  type OnModeChange,
} from "../hooks";
import { type CodeExecutionMode, toSdkPermissionMode } from "../tools";
import type { EffortLevel } from "../types";
import { buildAppendedInstructions } from "./instructions";
import { loadUserClaudeJsonMcpServers } from "./mcp-config";
import { DEFAULT_MODEL, FALLBACK_MODEL } from "./models";
import { createRtkRewriteHook, resolveRtkPrefix } from "./rtk";
import type { SettingsManager } from "./settings";

export interface ProcessSpawnedInfo {
  pid: number;
  command: string;
  sessionId: string;
}

/**
 * Gateway config threaded explicitly through session creation so that
 * concurrent Agent instances do not clobber each other's values via
 * global `process.env` mutation.
 */
export type GatewayEnv = {
  anthropicBaseUrl: string;
  anthropicAuthToken: string;
  openaiBaseUrl: string;
  openaiApiKey: string;
  /** Task-specific custom headers forwarded to the gateway (e.g. task_id, run_id). */
  anthropicCustomHeaders?: string;
  /**
   * Same task-metadata attribution headers as {@link anthropicCustomHeaders},
   * in record form for the codex/OpenAI path (which sets provider
   * `http_headers` rather than `ANTHROPIC_CUSTOM_HEADERS`). Includes `team_id`,
   * which the Claude path instead appends in {@link buildEnvironment}.
   */
  openaiCustomHeaders?: Record<string, string>;
  /** PostHog project ID for per-team attribution headers. */
  posthogProjectId?: string;
};

export interface BuildOptionsParams {
  cwd: string;
  mcpServers: Record<string, McpServerConfig>;
  permissionMode: CodeExecutionMode;
  posthogExecPermissionRegex?: RegExp;
  canUseTool: CanUseTool;
  logger: Logger;
  systemPrompt?: Options["systemPrompt"];
  userProvidedOptions?: Options;
  sessionId: string;
  isResume: boolean;
  forkSession?: boolean;
  additionalDirectories?: string[];
  disableBuiltInTools?: boolean;
  outputFormat?: OutputFormat;
  settingsManager: SettingsManager;
  onModeChange?: OnModeChange;
  onProcessSpawned?: (info: ProcessSpawnedInfo) => void;
  onProcessExited?: (pid: number) => void;
  effort?: EffortLevel;
  enrichmentDeps?: FileEnrichmentDeps;
  enrichedReadCache?: EnrichedReadCache;
  /** Records PostHog product usage from MCP exec calls (deduped, session-wide). */
  onPostHogResourceUsed?: (subTool: string, commandText?: string) => void;
  /** Cloud task session — enables the signed-commit guard. */
  cloudMode?: boolean;
  /** Reactive self-heal invoked when the guard blocks a raw git commit/push.
   * Returns whether signed-commit tooling is usable after the attempt. */
  onEnsureLocalToolsConnected?: () => Promise<boolean>;
  /** Per-session task state populated by createTaskHook from SDK Task* events. */
  taskState: TaskState;
  /** Called after createTaskHook mutates taskState so callers can emit a plan
   * sessionUpdate to the client. */
  onTaskStateChange?: () => Promise<void>;
  /** Explicit gateway config — prevents global process.env mutation. */
  gatewayEnv?: GatewayEnv;
}

export function buildSystemPrompt(
  customPrompt?: unknown,
  opts?: { spokenNarration?: boolean },
): Options["systemPrompt"] {
  const appendedInstructions = buildAppendedInstructions({
    spokenNarration: opts?.spokenNarration === true,
  });
  const defaultPrompt: Options["systemPrompt"] = {
    type: "preset",
    preset: "claude_code",
    append: appendedInstructions,
  };

  if (!customPrompt) {
    return defaultPrompt;
  }

  if (typeof customPrompt === "string") {
    return customPrompt + appendedInstructions;
  }

  if (
    typeof customPrompt === "object" &&
    customPrompt !== null &&
    "append" in customPrompt &&
    typeof customPrompt.append === "string"
  ) {
    return {
      ...defaultPrompt,
      append: customPrompt.append + appendedInstructions,
    };
  }

  return defaultPrompt;
}

function buildMcpServers(
  userServers: Record<string, McpServerConfig> | undefined,
  acpServers: Record<string, McpServerConfig>,
  projectScopedServers: Record<string, McpServerConfig>,
): Record<string, McpServerConfig> {
  return {
    ...projectScopedServers,
    ...(userServers || {}),
    ...acpServers,
  };
}

function buildEnvironment(gateway?: GatewayEnv): Record<string, string> {
  // Custom HTTP headers reach the model only through the Claude CLI subprocess,
  // which reads them from this env var (newline-delimited `name: value` lines)
  // — the SDK has no direct header option. We finalize them here, the single
  // chokepoint every session (desktop and cloud) funnels through.
  const headerLines: string[] = [];
  // Prefer explicit gateway config over process.env so concurrent sessions
  // do not clobber each other's task-specific headers.
  const existingCustomHeaders =
    gateway?.anthropicCustomHeaders ?? process.env.ANTHROPIC_CUSTOM_HEADERS;
  if (existingCustomHeaders) {
    headerLines.push(existingCustomHeaders);
  }
  // Attribute every captured $ai_generation event to the customer's team. The
  // gateway authenticates with a shared key, so without this the spend lands on
  // the key owner's team. The gateway lifts `x-posthog-property-*` headers onto
  // the event; both entrypoints export POSTHOG_PROJECT_ID before this runs
  // (workspace-server auth-adapter.ts, server/agent-server.ts). Mirrors django's
  // get_llm_client(team_id=...).
  const projectId = gateway?.posthogProjectId ?? process.env.POSTHOG_PROJECT_ID;
  if (projectId) {
    headerLines.push(buildGatewayPropertyHeaders({ team_id: projectId }));
  }
  // Route to AWS Bedrock as a fallback when Anthropic returns 5xx
  headerLines.push("x-posthog-use-bedrock-fallback: true");
  const customHeaders = headerLines.join("\n");

  // SDK 0.3.142 made MCP servers connect in the background by default. That
  // default is what we want: a slow or unreachable user MCP server (PostHog
  // MCP, custom stdio servers) would otherwise stall turn 1 by up to ~5s per
  // server. We honor an explicit override from the caller's environment for
  // sessions that genuinely need MCP tools available on turn 1.
  const mcpNonblocking = process.env.MCP_CONNECTION_NONBLOCKING;

  return {
    ...process.env,
    // Explicit gateway values win over whatever happens to be in process.env.
    // This prevents concurrent Agent instances from clobbering each other's
    // gateway config when process.env was mutated globally.
    ...(gateway?.anthropicBaseUrl && {
      ANTHROPIC_BASE_URL: gateway.anthropicBaseUrl,
    }),
    ...(gateway?.anthropicAuthToken && {
      ANTHROPIC_AUTH_TOKEN: gateway.anthropicAuthToken,
      ANTHROPIC_API_KEY: gateway.anthropicAuthToken,
    }),
    ...(gateway?.openaiBaseUrl && { OPENAI_BASE_URL: gateway.openaiBaseUrl }),
    ...(gateway?.openaiApiKey && { OPENAI_API_KEY: gateway.openaiApiKey }),
    ...((process.versions.electron || process.env.ELECTRON_RUN_AS_NODE) && {
      ELECTRON_RUN_AS_NODE: "1",
    }),
    CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL: "true",
    // Offload all MCP tools by default
    ENABLE_TOOL_SEARCH: "auto:0",
    // Enable idle state as end-of-turn signal (required for SDK 0.2.114+)
    CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS: "1",
    ...(mcpNonblocking !== undefined && {
      MCP_CONNECTION_NONBLOCKING: mcpNonblocking,
    }),
    ANTHROPIC_CUSTOM_HEADERS: customHeaders,
  };
}

function buildHooks(
  userHooks: Options["hooks"],
  onModeChange: OnModeChange | undefined,
  onPostHogResourceUsed:
    | ((subTool: string, commandText?: string) => void)
    | undefined,
  settingsManager: SettingsManager,
  posthogExecPermissionRegex: RegExp | undefined,
  logger: Logger,
  enrichmentDeps: FileEnrichmentDeps | undefined,
  enrichedReadCache: EnrichedReadCache | undefined,
  registeredAgents: ReadonlySet<string>,
  cloudMode: boolean,
  onEnsureLocalToolsConnected: (() => Promise<boolean>) | undefined,
  taskState: TaskState,
  onTaskStateChange: (() => Promise<void>) | undefined,
  rtkPrefix: string | undefined,
): Options["hooks"] {
  const postToolUseHooks = [
    createReadImageGuardHook(),
    createPostToolUseHook({
      onModeChange,
      onPostHogResourceUsed,
    }),
  ];
  if (enrichmentDeps && enrichedReadCache) {
    postToolUseHooks.push(
      createReadEnrichmentHook(enrichmentDeps, enrichedReadCache),
    );
  }

  const preToolUseHooks = [
    createPreToolUseHook(settingsManager, logger, posthogExecPermissionRegex),
    createSubagentRewriteHook(logger, registeredAgents),
  ];
  if (cloudMode) {
    preToolUseHooks.push(
      createSignedCommitGuardHook(logger, onEnsureLocalToolsConnected),
    );
  }
  // Registered last so the signed-commit guard evaluates the raw command first.
  if (rtkPrefix) {
    preToolUseHooks.push(createRtkRewriteHook(rtkPrefix, logger));
  }

  const taskHook = createTaskHook(taskState, onTaskStateChange);

  return {
    ...userHooks,
    PostToolUse: [
      ...(userHooks?.PostToolUse || []),
      { hooks: postToolUseHooks },
    ],
    PreToolUse: [...(userHooks?.PreToolUse || []), { hooks: preToolUseHooks }],
    TaskCreated: [...(userHooks?.TaskCreated || []), { hooks: [taskHook] }],
    TaskCompleted: [...(userHooks?.TaskCompleted || []), { hooks: [taskHook] }],
  };
}

/**
 * Read-only exploration agent. Registered under the `ph-explore`
 * name rather than `Explore` to work around a Claude Agent SDK bug where
 * `options.agents` cannot shadow built-in agent definitions. The
 * `createSubagentRewriteHook` rewrites `subagent_type: "Explore"` to
 * `"ph-explore"` so callers don't have to know about the alias.
 */
const PH_EXPLORE_AGENT: NonNullable<Options["agents"]>[string] = {
  description:
    'Fast agent for exploring and understanding codebases. Use this when you need to find files by pattern (eg. "src/components/**/*.tsx"), search for code or keywords (eg. "where is the auth middleware?"), or answer questions about how the codebase works (eg. "how does the session service handle reconnects?"). When calling this agent, specify a thoroughness level: "quick" for targeted lookups, "medium" for broader exploration, or "very thorough" for comprehensive analysis across multiple locations.',
  model: "sonnet",
  prompt: `You are a fast, read-only codebase exploration agent.

Your job is to find files, search code, read the most relevant sources, and report findings clearly.

Rules:
- Never create, modify, delete, move, or copy files.
- Never use shell redirection or any command that changes system state.
- Use Glob for broad file pattern matching.
- Use Grep for searching file contents.
- Use Read when you know the exact file path to inspect.
- Use Bash only for safe read-only commands like ls, git status, git log, git diff, find, cat, head, and tail.
- Adapt your search approach based on the thoroughness level specified by the caller.
- Return file paths as absolute paths in your final response.
- Avoid using emojis.
- Wherever possible, spawn multiple parallel tool calls for grepping and reading files.
- Search efficiently, then read only the most relevant files.
- Return findings directly in your final response — do not create files.`,
  tools: [
    "Bash",
    "Glob",
    "Grep",
    "Read",
    "WebFetch",
    "WebSearch",
    "NotebookRead",
    "TaskCreate",
    "TaskUpdate",
    "TaskGet",
    "TaskList",
  ],
};

function buildAgents(
  userAgents: Options["agents"],
): NonNullable<Options["agents"]> {
  return {
    "ph-explore": PH_EXPLORE_AGENT,
    ...(userAgents || {}),
  };
}

function getAbortController(
  userProvidedController: AbortController | undefined,
): AbortController {
  const controller = userProvidedController ?? new AbortController();
  if (controller.signal.aborted) {
    throw new Error("Cancelled");
  }
  return controller;
}

function buildSpawnWrapper(
  sessionId: string,
  onProcessSpawned: (info: ProcessSpawnedInfo) => void,
  onProcessExited?: (pid: number) => void,
  logger?: Logger,
): (options: SpawnOptions) => SpawnedProcess {
  return (spawnOpts: SpawnOptions): SpawnedProcess => {
    const child = spawn(spawnOpts.command, spawnOpts.args, {
      cwd: spawnOpts.cwd,
      env: spawnOpts.env as NodeJS.ProcessEnv,
      stdio: ["pipe", "pipe", "pipe"],
    });

    if (child.pid) {
      onProcessSpawned({
        pid: child.pid,
        command: `${spawnOpts.command} ${spawnOpts.args.join(" ")}`,
        sessionId,
      });
    }

    child.stderr?.on("data", (data: Buffer) => {
      const msg = data.toString().trim();
      if (msg && logger) {
        logger.warn(`[claude-code:${child.pid}] stderr: ${msg}`);
      }
    });

    if (onProcessExited) {
      child.on("exit", () => {
        if (child.pid) {
          onProcessExited(child.pid);
        }
      });
    }

    // Listen for abort signal
    if (spawnOpts.signal) {
      spawnOpts.signal.addEventListener("abort", () => {
        child.kill("SIGTERM");
      });
    }

    if (!child.stdin || !child.stdout) {
      throw new Error(
        `Failed to get stdio streams for spawned process (pid=${child.pid})`,
      );
    }

    return {
      stdin: child.stdin,
      stdout: child.stdout,
      get killed() {
        return child.killed;
      },
      get exitCode() {
        return child.exitCode;
      },
      kill(signal: NodeJS.Signals) {
        return child.kill(signal);
      },
      // biome-ignore lint/suspicious/noExplicitAny: ChildProcess event listener types require any[]
      on(event: "exit" | "error", listener: (...args: any[]) => void) {
        child.on(event, listener);
      },
      // biome-ignore lint/suspicious/noExplicitAny: ChildProcess event listener types require any[]
      once(event: "exit" | "error", listener: (...args: any[]) => void) {
        child.once(event, listener);
      },
      // biome-ignore lint/suspicious/noExplicitAny: ChildProcess event listener types require any[]
      off(event: "exit" | "error", listener: (...args: any[]) => void) {
        child.off(event, listener);
      },
    };
  };
}

function ensureLocalSettings(cwd: string): void {
  const claudeDir = path.join(cwd, ".claude");
  const localSettingsPath = path.join(claudeDir, "settings.local.json");
  try {
    if (!fs.existsSync(localSettingsPath)) {
      fs.mkdirSync(claudeDir, { recursive: true });
      fs.writeFileSync(localSettingsPath, "{}\n", { flag: "wx" });
    }
  } catch {
    // Best-effort — don't fail session creation if we can't write
  }
}

// The legacy CLI ships as cli.js; native binaries have no file extension.
function isLegacyJavaScriptClaudeExecutable(executablePath: string): boolean {
  return executablePath.endsWith(".js");
}

export function buildSessionOptions(params: BuildOptionsParams): Options {
  ensureLocalSettings(params.cwd);

  // Resolve which built-in tools to expose.
  // Explicit tools array from userProvidedOptions takes precedence.
  // disableBuiltInTools is a legacy shorthand for tools: [] — kept for
  // backward compatibility but callers should prefer the tools array.
  const tools: Options["tools"] =
    params.userProvidedOptions?.tools ??
    (params.disableBuiltInTools
      ? []
      : { type: "preset", preset: "claude_code" });

  const agents = buildAgents(params.userProvidedOptions?.agents);
  const registeredAgentNames = new Set(Object.keys(agents));
  const claudeCodeExecutable = process.env.CLAUDE_CODE_EXECUTABLE;

  const options: Options = {
    ...params.userProvidedOptions,
    betas: ["context-1m-2025-08-07"],
    systemPrompt: params.systemPrompt ?? buildSystemPrompt(),
    settingSources: ["user", "project", "local"],
    stderr: (err) => params.logger.error(err),
    cwd: params.cwd,
    includePartialMessages: true,
    allowDangerouslySkipPermissions: !IS_ROOT || !!process.env.IS_SANDBOX,
    permissionMode: toSdkPermissionMode(params.permissionMode),
    canUseTool: params.canUseTool,
    tools,
    agents,
    extraArgs: {
      ...params.userProvidedOptions?.extraArgs,
      "replay-user-messages": "",
    },
    mcpServers: buildMcpServers(
      params.userProvidedOptions?.mcpServers,
      params.mcpServers,
      loadUserClaudeJsonMcpServers(params.cwd, params.logger),
    ),
    env: buildEnvironment(params.gatewayEnv),
    hooks: buildHooks(
      params.userProvidedOptions?.hooks,
      params.onModeChange,
      params.onPostHogResourceUsed,
      params.settingsManager,
      params.posthogExecPermissionRegex,
      params.logger,
      params.enrichmentDeps,
      params.enrichedReadCache,
      registeredAgentNames,
      params.cloudMode ?? false,
      params.onEnsureLocalToolsConnected,
      params.taskState,
      params.onTaskStateChange,
      resolveRtkPrefix(process.env),
    ),
    outputFormat: params.outputFormat,
    abortController: getAbortController(
      params.userProvidedOptions?.abortController,
    ),
    ...(params.onProcessSpawned && {
      spawnClaudeCodeProcess: buildSpawnWrapper(
        params.sessionId,
        params.onProcessSpawned,
        params.onProcessExited,
        params.logger,
      ),
    }),
  };

  if (claudeCodeExecutable) {
    options.pathToClaudeCodeExecutable = claudeCodeExecutable;
    if (isLegacyJavaScriptClaudeExecutable(claudeCodeExecutable)) {
      options.executable = "node";
    }
  }

  if (params.isResume) {
    options.resume = params.sessionId;
    options.forkSession = params.forkSession ?? false;
  } else {
    options.sessionId = params.sessionId;
    options.model = DEFAULT_MODEL;
  }

  if (!options.fallbackModel && options.model !== FALLBACK_MODEL) {
    options.fallbackModel = FALLBACK_MODEL;
  }

  if (params.additionalDirectories) {
    options.additionalDirectories = params.additionalDirectories;
  }

  if (params.effort) {
    options.effort = params.effort;
  }

  clearStatsigCache();
  return options;
}

function clearStatsigCache(): void {
  const statsigPath = path.join(
    process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude"),
    "statsig",
  );
  fs.rm(statsigPath, { recursive: true, force: true }, () => {
    // Best-effort, ignore errors
  });
}
