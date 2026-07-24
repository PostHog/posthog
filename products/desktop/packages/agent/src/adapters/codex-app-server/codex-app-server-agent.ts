import type {
  AgentSideConnection,
  ForkSessionRequest,
  ForkSessionResponse,
  InitializeRequest,
  InitializeResponse,
  ListSessionsRequest,
  ListSessionsResponse,
  LoadSessionRequest,
  LoadSessionResponse,
  NewSessionRequest,
  NewSessionResponse,
  PromptRequest,
  PromptResponse,
  RequestPermissionResponse,
  ResumeSessionRequest,
  ResumeSessionResponse,
  SessionNotification,
  SetSessionConfigOptionRequest,
  SetSessionConfigOptionResponse,
  StopReason,
} from "@agentclientprotocol/sdk";
import { RequestError } from "@agentclientprotocol/sdk";
import {
  classifyGatewayLimitError,
  mcpToolKey,
  posthogToolMeta,
} from "@posthog/shared";
import {
  type NativeGoalState,
  POSTHOG_NOTIFICATIONS,
} from "../../acp-extensions";
import type { ModelInfo } from "../../gateway-models";
import { DEFAULT_CODEX_MODEL } from "../../gateway-models";
import {
  extractPostHogSubTool,
  isPostHogExecDescriptor,
  matchesPostHogExecPermission,
  resolvePostHogExecPermissionRegex,
} from "../../posthog-exec-permission";
import type { ProcessSpawnedCallback } from "../../types";
import { ALLOW_BYPASS } from "../../utils/common";
import { Logger } from "../../utils/logger";
import {
  nodeReadableToWebReadable,
  nodeWritableToWebWritable,
} from "../../utils/streams";
import { BaseAcpAgent, type BaseSettingsManager } from "../base-acp-agent";
import {
  type ContextBreakdownBaseline,
  emptyBaseline,
  estimateTokens,
} from "../claude/context-breakdown";
import { isLocalSkillCommandChunk } from "../local-skill";
import { resolveSpokenNarration } from "../session-meta";
import {
  AppServerClient,
  type AppServerClientHandlers,
  AppServerRequestError,
  type AppServerRpc,
} from "./app-server-client";
import { handleServerRequest } from "./approvals";
import {
  buildSdkSessionParams,
  buildTurnCompleteParams,
  buildUsageBreakdownParams,
} from "./ext-notifications";
import { type CodexUserInput, toCodexInput } from "./input";
import { buildLocalToolsServer, type LocalToolsMeta } from "./local-tools-mcp";
import {
  type AppServerItem,
  changePaths,
  diffContent,
  mapAppServerNotification,
  mapHistoryItem,
} from "./mapping";
import { toCodexMcpServers } from "./mcp-config";
import { McpManager } from "./mcp-manager";
import {
  APP_SERVER_METHODS,
  APP_SERVER_NOTIFICATIONS,
  APP_SERVER_REQUESTS,
} from "./protocol";
import {
  type CodexSandboxPolicy,
  type RawModel,
  SessionConfigState,
} from "./session-config";
import {
  type CodexAppServerProcess,
  type CodexAppServerProcessOptions,
  spawnCodexAppServerProcess,
} from "./spawn";
import { parseStructuredOutput } from "./structured-output";
import { TurnController } from "./turn-controller";
import { UsageTracker } from "./usage-tracker";

function isStaleTurnSteerError(error: unknown): boolean {
  if (!(error instanceof AppServerRequestError) || error.code !== -32600) {
    return false;
  }
  return (
    error.message === "no active turn to steer" ||
    /^expected active turn id `.*` but found `.*`$/.test(error.message)
  );
}

type AppServerSessionMeta = {
  // The host sends either a plain string or the Claude-style `{ append }` form.
  systemPrompt?: string | { append?: string };
  jsonSchema?: Record<string, unknown> | null;
  permissionMode?: string;
  taskRunId?: string;
  taskId?: string;
  persistence?: { taskId?: string };
  environment?: "local" | "cloud";
  channelMode?: boolean;
  spokenNarration?: boolean;
  baseBranch?: string;
  posthogExecPermissionRegex?: string;
  nativeGoal?: NativeGoalState;
};

/** The subset of codex's `Thread` the adapter reads: id + persisted `turns` for history replay. */
type AppServerThread = {
  id?: string;
  turns?: Array<{ items?: Parameters<typeof mapHistoryItem>[1][] }>;
};

type ThreadGoal = {
  objective: string;
  status: NativeGoalState["status"];
};

type GoalCommand =
  | { kind: "get" }
  | { kind: "clear" }
  | { kind: "pause" }
  | { kind: "resume" }
  | { kind: "set"; objective: string };

const MAX_PLAN_PROPOSAL_CHARS = 100_000;

type CodexSkill = {
  name?: string;
  description?: string;
  enabled?: boolean;
};

const GOAL_COMMAND = {
  name: "goal",
  description: "Set or view the goal for a long-running task",
  input: { hint: "[<objective>|clear|pause|resume]" },
};

function isHiddenPromptBlock(block: PromptRequest["prompt"][number]): boolean {
  const meta = block._meta as { ui?: { hidden?: boolean } } | undefined;
  return meta?.ui?.hidden === true;
}

function visiblePromptBlocks(
  prompt: PromptRequest["prompt"],
): PromptRequest["prompt"] {
  return prompt.filter((block) => !isHiddenPromptBlock(block));
}

function parseGoalCommand(prompt: PromptRequest["prompt"]): GoalCommand | null {
  const visible = visiblePromptBlocks(prompt);
  if (visible.some((block) => block.type !== "text")) return null;
  const text = visible
    .map((block) => (block.type === "text" ? block.text : ""))
    .join("\n")
    .trim();
  const match = text.match(/^\/goal(?:\s+([\s\S]*))?$/);
  if (!match) return null;
  const argument = match[1]?.trim();
  if (!argument) return { kind: "get" };
  switch (argument.toLowerCase()) {
    case "clear":
      return { kind: "clear" };
    case "pause":
      return { kind: "pause" };
    case "resume":
      return { kind: "resume" };
    default:
      return { kind: "set", objective: argument };
  }
}

function mergePromptUsage(
  left: PromptResponse["usage"],
  right: PromptResponse["usage"],
): PromptResponse["usage"] {
  if (!left) return right;
  if (!right) return left;
  return {
    inputTokens: left.inputTokens + right.inputTokens,
    outputTokens: left.outputTokens + right.outputTokens,
    cachedReadTokens:
      (left.cachedReadTokens ?? 0) + (right.cachedReadTokens ?? 0),
    cachedWriteTokens:
      (left.cachedWriteTokens ?? 0) + (right.cachedWriteTokens ?? 0),
    thoughtTokens: (left.thoughtTokens ?? 0) + (right.thoughtTokens ?? 0),
    totalTokens: left.totalTokens + right.totalTokens,
  };
}

function mergePromptResponses(
  left: PromptResponse,
  right: PromptResponse,
): PromptResponse {
  return { ...right, usage: mergePromptUsage(left.usage, right.usage) };
}

// The native app-server owns its config; BaseAcpAgent only calls dispose() on this.
class NoopSettingsManager implements BaseSettingsManager {
  constructor(private cwd: string) {}
  dispose(): void {}
  getCwd(): string {
    return this.cwd;
  }
  async setCwd(cwd: string): Promise<void> {
    this.cwd = cwd;
  }
  async initialize(): Promise<void> {}
}

export interface CodexAppServerAgentOptions {
  processOptions: CodexAppServerProcessOptions;
  model?: string;
  reasoningEffort?: string;
  gatewayModels?: ReadonlyArray<ModelInfo>;
  processCallbacks?: ProcessSpawnedCallback;
  logger?: Logger;
  onStructuredOutput?: (output: Record<string, unknown>) => Promise<void>;
  /** Test seam: build the JSON-RPC client (defaults to spawning the process). */
  rpcFactory?: (handlers: AppServerClientHandlers) => AppServerRpc;
}

/**
 * ACP Agent backed by the native Codex `app-server` JSON-RPC protocol,
 * presenting the ACP surface PostHog expects.
 */
export class CodexAppServerAgent extends BaseAcpAgent {
  readonly adapterName = "codex";
  private readonly rpc: AppServerRpc;
  private readonly proc?: CodexAppServerProcess;
  private readonly config: SessionConfigState;
  private readonly onStructuredOutput?: (
    output: Record<string, unknown>,
  ) => Promise<void>;
  /** Codex-specific guidance injected at spawn time; replayed per-thread. */
  private readonly developerInstructions?: string;
  private threadId?: string;
  /** JSON schema constraining the final message; set per session via `_meta`. */
  private jsonSchema?: Record<string, unknown>;
  /** Final assistant message text for the in-flight turn (structured output). */
  private lastAgentMessage = "";
  /** True between a contextCompaction item's start and its boundary (dedupes the boundary). */
  private compactionActive = false;
  /** Maps the host's taskRunId to this session, replayed for cloud notifications. */
  private taskRunId?: string;
  /** Deployment environment; on "cloud" a non-danger sandbox would panic, so we skip the override. */
  private environment?: "local" | "cloud";
  /** Gates PostHog exec sub-tools; set per session, defaults to the destructive-verbs regex. */
  private posthogExecPermissionRegex =
    resolvePostHogExecPermissionRegex(undefined);
  private readonly commandOutputs = new Map<string, string>();
  private readonly subagentParents = new Map<string, string>();
  private readonly pendingSubagentNotifications = new Map<
    string,
    SessionNotification[]
  >();
  /** Extra writable roots for this session, folded into workspaceWrite sandbox turns. */
  private additionalDirectories?: string[];
  /** The session workspace stays writable when extra roots are applied per turn. */
  private workspaceDirectory?: string;
  /** The in-flight turn's <proposed_plan>, streamed or completed (drives the implement handoff). */
  private planProposal?: { itemId: string; text: string };
  /** Structured plan tool call already emitted while the proposal streams. */
  private streamedPlanToolCallId?: string;
  /** Idle signal deferred while the plan handoff keeps this prompt busy. */
  private deferredTurnComplete?: { usage: PromptResponse["usage"] };
  /** Settles the pending plan-approval race on cancel/close/preempting prompt. */
  private planHandoffCancel?: () => void;
  private readonly mcp = new McpManager();
  private readonly turns = new TurnController();
  private readonly usage = new UsageTracker();
  /** Pause/clear can race a goal continuation already queued by app-server. */
  private cancelNextGoalTurn = false;
  /** Native goal ticks start outside prompt(), so TurnController does not own them. */
  private nativeGoalTurnId?: string;

  constructor(
    client: AgentSideConnection,
    options: CodexAppServerAgentOptions,
  ) {
    super(client);
    this.logger =
      options.logger ??
      new Logger({ debug: true, prefix: "[CodexAppServerAgent]" });
    this.config = new SessionConfigState(
      options.model ?? DEFAULT_CODEX_MODEL,
      options.reasoningEffort,
      options.gatewayModels,
    );
    this.onStructuredOutput = options.onStructuredOutput;
    this.developerInstructions = options.processOptions.developerInstructions;

    const handlers: AppServerClientHandlers = {
      logger: this.logger,
      onNotification: (method, params) =>
        this.handleNotification(method, params),
      onRequest: (method, params) => this.handleApproval(method, params),
      onClose: () => this.handleServerClosed(),
    };

    if (options.rpcFactory) {
      this.rpc = options.rpcFactory(handlers);
    } else {
      this.proc = spawnCodexAppServerProcess({
        ...options.processOptions,
        logger: this.logger,
        processCallbacks: options.processCallbacks,
      });
      this.rpc = new AppServerClient(
        {
          readable: nodeReadableToWebReadable(this.proc.stdout),
          writable: nodeWritableToWebWritable(this.proc.stdin),
        },
        handlers,
      );
    }

    this.session = {
      abortController: new AbortController(),
      settingsManager: new NoopSettingsManager(
        options.processOptions.cwd ?? process.cwd(),
      ),
      notificationHistory: [],
      cancelled: false,
    };
  }

  async initialize(request: InitializeRequest): Promise<InitializeResponse> {
    await this.rpc.request(APP_SERVER_METHODS.INITIALIZE, {
      clientInfo: {
        name: "posthog-code",
        title: "PostHog",
        version: "0.1.0",
      },
      // Opt into codex's experimental API so experimental turn/start fields are honored.
      capabilities: { experimentalApi: true, requestAttestation: false },
    });
    this.rpc.notify(APP_SERVER_NOTIFICATIONS.INITIALIZED, {});
    return {
      protocolVersion: request.protocolVersion,
      agentCapabilities: {
        promptCapabilities: {
          image: true,
          embeddedContext: true,
        },
        // Only http: we don't claim SSE rather than mistranslate it into the http shape.
        mcpCapabilities: {
          http: true,
        },
        loadSession: true,
        sessionCapabilities: {
          list: {},
          fork: {},
          resume: {},
          additionalDirectories: {},
        },
        _meta: {
          posthog: {
            resumeSession: true,
            steering: "native",
          },
        },
      },
      agentInfo: {
        name: "codex",
        title: "Codex (app-server)",
        version: "0.1.0",
      },
      authMethods: [],
    };
  }

  async newSession(params: NewSessionRequest): Promise<NewSessionResponse> {
    const { threadId } = await this.setupThread(
      APP_SERVER_METHODS.THREAD_START,
      {
        cwd: params.cwd,
        mcpServers: params.mcpServers,
        meta: params._meta as AppServerSessionMeta | undefined,
        additionalDirectories: params.additionalDirectories ?? undefined,
      },
    );
    return { sessionId: threadId, configOptions: this.config.options };
  }

  async resumeSession(
    params: ResumeSessionRequest,
  ): Promise<ResumeSessionResponse> {
    await this.setupThread(APP_SERVER_METHODS.THREAD_RESUME, {
      cwd: params.cwd,
      mcpServers: params.mcpServers,
      meta: params._meta as AppServerSessionMeta | undefined,
      threadId: params.sessionId,
      additionalDirectories: params.additionalDirectories ?? undefined,
    });
    return { configOptions: this.config.options };
  }

  /** Re-attach to an existing thread without starting a turn: resume it, then replay the transcript. */
  async loadSession(params: LoadSessionRequest): Promise<LoadSessionResponse> {
    const { thread } = await this.setupThread(
      APP_SERVER_METHODS.THREAD_RESUME,
      {
        cwd: params.cwd,
        mcpServers: params.mcpServers,
        meta: params._meta as AppServerSessionMeta | undefined,
        threadId: params.sessionId,
        additionalDirectories: params.additionalDirectories ?? undefined,
      },
    );
    this.replayHistory(thread);
    return { configOptions: this.config.options };
  }

  async unstable_forkSession(
    params: ForkSessionRequest,
  ): Promise<ForkSessionResponse> {
    const { threadId } = await this.setupThread(
      APP_SERVER_METHODS.THREAD_FORK,
      {
        cwd: params.cwd,
        mcpServers: params.mcpServers,
        meta: params._meta as AppServerSessionMeta | undefined,
        threadId: params.sessionId,
        additionalDirectories: params.additionalDirectories ?? undefined,
      },
    );
    return { sessionId: threadId, configOptions: this.config.options };
  }

  /** Replay a resumed thread's persisted turns (from the thread/resume response) as session updates. */
  private replayHistory(thread: AppServerThread | undefined): void {
    if (!this.sessionId || !thread?.turns?.length) return;
    for (const turn of thread.turns) {
      for (const item of turn.items ?? []) {
        for (const update of mapHistoryItem(this.sessionId, item)) {
          void this.client.sessionUpdate(update).catch(() => undefined);
        }
      }
    }
  }

  async listSessions(
    params: ListSessionsRequest,
  ): Promise<ListSessionsResponse> {
    try {
      const res = await this.rpc.request<{
        data?: Array<{
          id?: string;
          cwd?: string;
          name?: string | null;
          preview?: string;
        }>;
      }>(APP_SERVER_METHODS.THREAD_LIST, { cwd: params.cwd });
      const sessions = (res?.data ?? [])
        .filter((t) => t?.id)
        .map((t) => ({
          sessionId: t.id as string,
          cwd: t.cwd ?? params.cwd ?? "",
          ...(t.name || t.preview
            ? { title: t.name ?? t.preview ?? undefined }
            : {}),
        }));
      return { sessions };
    } catch (err) {
      this.logger.warn("thread/list failed", { error: String(err) });
      return { sessions: [] };
    }
  }

  /** Shared thread setup for start/resume/fork. `threadId` present => resume/fork; absent => new thread. */
  private async setupThread(
    method: string,
    params: {
      cwd?: string;
      mcpServers?: NewSessionRequest["mcpServers"];
      meta?: AppServerSessionMeta;
      threadId?: string;
      additionalDirectories?: string[];
    },
  ): Promise<{ threadId: string; thread: AppServerThread | undefined }> {
    this.cancelNextGoalTurn = false;
    this.nativeGoalTurnId = undefined;
    this.subagentParents.clear();
    this.pendingSubagentNotifications.clear();
    this.jsonSchema = params.meta?.jsonSchema ?? undefined;
    this.taskRunId = params.meta?.taskRunId;
    this.environment = params.meta?.environment;
    this.additionalDirectories = params.additionalDirectories;
    this.workspaceDirectory = params.cwd;
    this.config.setInitialMode(params.meta?.permissionMode);
    // Codex doesn't attribute input tokens by source; the baseline seeds the resident floor + system prompt.
    this.usage.setBaseline(buildBaseline(params.meta));
    // Flatten the {append} form (else "[object Object]") and dedupe identical parts
    // (the host pre-flattens into developerInstructions, so the prod prompt would duplicate).
    const developerInstructions = [
      ...new Set(
        [
          this.developerInstructions,
          flattenSystemPrompt(params.meta?.systemPrompt),
        ].filter((s): s is string => !!s),
      ),
    ].join("\n\n");
    // Degrade gracefully: an unresolvable bundled local-tools script skips it with a
    // warning rather than killing thread setup.
    let localTools: ReturnType<typeof buildLocalToolsServer> = null;
    try {
      localTools = buildLocalToolsServer(
        { cwd: params.cwd },
        this.localToolsMeta(params.meta),
      );
    } catch (err) {
      this.logger.warn(
        "local-tools server unavailable; continuing without it",
        { error: String(err) },
      );
    }
    this.posthogExecPermissionRegex = resolvePostHogExecPermissionRegex(
      params.meta?.posthogExecPermissionRegex,
      (message) =>
        this.logger.warn(
          "Invalid posthogExecPermissionRegex in session metadata; using default",
          { message },
        ),
    );
    const mcpServers = toCodexMcpServers(
      [...(params.mcpServers ?? []), ...(localTools ? [localTools] : [])],
      { gatePosthogExec: true },
    );
    const config = buildThreadConfig(mcpServers, params.additionalDirectories);

    const result = await this.rpc.request<{ thread?: AppServerThread }>(
      method,
      {
        model: this.config.model,
        cwd: params.cwd,
        ...(params.threadId ? { threadId: params.threadId } : {}),
        ...(developerInstructions ? { developerInstructions } : {}),
        ...(config ? { config } : {}),
      },
    );
    const thread = result?.thread;
    const threadId = thread?.id ?? params.threadId;
    if (!threadId) {
      throw new Error(`codex app-server ${method} returned no thread id`);
    }
    this.threadId = threadId;
    this.sessionId = threadId;
    this.restoreSubagentRelationships(thread);
    if (method === APP_SERVER_METHODS.THREAD_START && params.meta?.nativeGoal) {
      await this.restoreGoal(params.meta.nativeGoal);
    }
    await this.loadModelConfig();
    this.emitConfigOptions();
    await this.emitAvailableCommands();
    await this.emitSdkSession();
    this.logger.info("Codex app-server thread ready", {
      method,
      threadId,
      mcpServers: mcpServers ? Object.keys(mcpServers) : [],
      hasOutputSchema: !!this.jsonSchema,
      hasLocalTools: !!localTools,
    });
    return { threadId, thread };
  }

  private localToolsMeta(
    meta: AppServerSessionMeta | undefined,
  ): LocalToolsMeta | undefined {
    if (!meta) return undefined;
    return {
      environment: meta.environment,
      channelMode: meta.channelMode,
      spokenNarration: resolveSpokenNarration(meta),
      taskId: meta.taskId,
      taskRunId: meta.taskRunId,
      persistence: meta.persistence,
      baseBranch: meta.baseBranch,
    };
  }

  private async emitSdkSession(): Promise<void> {
    if (!this.taskRunId || !this.sessionId) return;
    await this.client
      .extNotification(
        POSTHOG_NOTIFICATIONS.SDK_SESSION,
        buildSdkSessionParams(
          this.sessionId,
          this.taskRunId,
        ) as unknown as Record<string, unknown>,
      )
      .catch((err) =>
        this.logger.warn("sdk_session extNotification failed", err),
      );
  }

  async setSessionConfigOption(
    params: SetSessionConfigOptionRequest,
  ): Promise<SetSessionConfigOptionResponse> {
    const { configId } = params as { configId?: string };
    const value = (params as { value?: unknown }).value;
    const { modeChanged } = this.config.setOption(configId, value);
    // collaborationMode rides the next turn/start, so a mode switch only needs current_mode_update here.
    if (modeChanged) {
      this.emitCurrentMode(this.config.mode);
      if (this.config.mode !== "plan") this.planHandoffCancel?.();
    }
    this.emitConfigOptions();
    return { configOptions: this.config.options };
  }

  /** Emit current_mode_update on mode change for the host's mode cache. */
  private emitCurrentMode(modeId: string): void {
    if (!this.sessionId) return;
    void this.client
      .sessionUpdate({
        sessionId: this.sessionId,
        update: { sessionUpdate: "current_mode_update", currentModeId: modeId },
      } as unknown as Parameters<AgentSideConnection["sessionUpdate"]>[0])
      .catch(() => undefined);
  }

  private async loadModelConfig(): Promise<void> {
    try {
      const res = await this.rpc.request<{ data?: RawModel[] }>(
        APP_SERVER_METHODS.MODEL_LIST,
        {},
      );
      this.config.loadModels(res?.data ?? []);
    } catch (err) {
      this.logger.warn("model/list failed; using current model only", {
        error: String(err),
      });
      this.config.clearModels();
    }
  }

  private emitConfigOptions(): void {
    if (!this.sessionId) return;
    void this.client
      .sessionUpdate({
        sessionId: this.sessionId,
        update: {
          sessionUpdate: "config_option_update",
          configOptions: this.config.options,
        },
      } as unknown as Parameters<AgentSideConnection["sessionUpdate"]>[0])
      .catch((err) => this.logger.warn("config_option_update failed", err));
  }

  /** skills/list → available_commands_update so the slash-command menu fills. */
  private async emitAvailableCommands(): Promise<void> {
    if (!this.sessionId) return;
    let commands: Array<{
      name: string;
      description: string;
      input?: { hint: string };
    }> = [GOAL_COMMAND];
    try {
      const res = await this.rpc.request<{
        data?: Array<{ skills?: CodexSkill[] }>;
      }>(APP_SERVER_METHODS.SKILLS_LIST, {});
      const skills = (res?.data ?? [])
        .flatMap((entry) => entry?.skills ?? [])
        // Drop explicitly-disabled skills; lenient `!== false` so a malformed payload still shows.
        .filter(
          (skill): skill is CodexSkill & { name: string } =>
            !!skill.name &&
            skill.name !== GOAL_COMMAND.name &&
            skill.enabled !== false,
        )
        .map((skill) => ({
          name: skill.name,
          description: skill.description ?? "",
        }));
      commands = [GOAL_COMMAND, ...skills];
    } catch (err) {
      this.logger.warn("skills/list failed", { error: String(err) });
    }
    void this.client
      .sessionUpdate({
        sessionId: this.sessionId,
        update: {
          sessionUpdate: "available_commands_update",
          availableCommands: commands,
        },
      } as unknown as Parameters<AgentSideConnection["sessionUpdate"]>[0])
      .catch(() => undefined);
  }

  async prompt(params: PromptRequest): Promise<PromptResponse> {
    if (!this.threadId) {
      throw new Error("prompt() called before newSession()");
    }
    const goalCommand = parseGoalCommand(params.prompt);
    if (goalCommand) {
      this.broadcastUserInput(visiblePromptBlocks(params.prompt));
      await this.handleGoalCommand(goalCommand);
      return { stopReason: "end_turn" };
    }
    this.cancelNextGoalTurn = false;
    // Reopen the notification gate (a prior interrupt may have left session.cancelled set).
    this.session.cancelled = false;
    // A new prompt while the plan handoff awaits approval implicitly declines it:
    // settle the race so the previous prompt() returns and this one owns the turn.
    this.planHandoffCancel?.();
    // Prepend _meta.prContext (host PR-follow-up / Slack runs) to the FORWARDED prompt,
    // else codex cloud follow-ups lose the PR-review context. The echo omits it.
    const meta = params._meta as
      | {
          prContext?: unknown;
          localSkillContext?: unknown;
          localSkillName?: unknown;
        }
      | undefined;
    const prContext = meta?.prContext;
    // Inline installed local skill definitions (mirrors the Claude adapter):
    // codex's skill catalog is fixed at thread start, so mid-session installs
    // are invisible without this. A bare `/name` command chunk is dropped —
    // the injected context already carries the user's args.
    const localSkillContext =
      typeof meta?.localSkillContext === "string"
        ? meta.localSkillContext
        : null;
    const localSkillName =
      typeof meta?.localSkillName === "string" ? meta.localSkillName : null;
    let forwarded = params.prompt;
    if (localSkillContext) {
      if (localSkillName) {
        let skippedLocalSkillCommand = false;
        forwarded = forwarded.filter((chunk) => {
          if (
            !skippedLocalSkillCommand &&
            isLocalSkillCommandChunk(chunk, localSkillName)
          ) {
            skippedLocalSkillCommand = true;
            return false;
          }
          return true;
        });
      }
      forwarded = [
        { type: "text" as const, text: localSkillContext },
        ...forwarded,
      ];
    }
    const promptBlocks =
      typeof prContext === "string" && prContext.length > 0
        ? [{ type: "text" as const, text: prContext }, ...forwarded]
        : forwarded;
    const input = toCodexInput(promptBlocks);
    if (input.length === 0) {
      // turn/start rejects empty input, so end the turn cleanly.
      this.logger.warn("prompt() had no usable input blocks; ending turn");
      return { stopReason: "end_turn" };
    }
    // Count by type (not input.length): a resource block can fan out to multiple blocks.
    const dropped = params.prompt.filter(
      (b) =>
        b.type !== "text" &&
        b.type !== "image" &&
        b.type !== "resource" &&
        b.type !== "resource_link",
    ).length;
    if (dropped > 0) {
      this.logger.warn("Dropped non-text/non-image prompt blocks", { dropped });
    }
    if (this.turns.isRunning) {
      // A turn is already running: fold the message in via turn/steer (precondition: the
      // active turnId). Refresh from the response's rotated turnId so a later steer/interrupt
      // still targets the live turn (no turn/started is re-emitted for a steer).
      let steerRes: { turnId?: string };
      try {
        steerRes = await this.rpc.request<{ turnId?: string }>(
          APP_SERVER_METHODS.TURN_STEER,
          {
            threadId: this.threadId,
            input,
            expectedTurnId: this.turns.activeTurnId,
          },
        );
      } catch (error) {
        if (
          (params._meta as { steer?: unknown } | undefined)?.steer === true &&
          isStaleTurnSteerError(error)
        ) {
          return { stopReason: "end_turn", _meta: { steer: false } };
        }
        throw error;
      }
      this.turns.onSteered(steerRes?.turnId);
      this.broadcastUserInput(params.prompt);
      return { stopReason: "end_turn", _meta: { steer: true } };
    }
    if ((params._meta as { steer?: unknown } | undefined)?.steer === true) {
      return { stopReason: "end_turn", _meta: { steer: false } };
    }
    if (this.turns.isPending) {
      // A turn is pending but has no turnId yet, so we can't steer; fail fast.
      throw new Error("prompt() called while a turn is already in progress");
    }

    // Codex does not echo user input, so emit it only once delivery can proceed.
    this.broadcastUserInput(params.prompt);
    const response = await this.runTurn(input);
    return this.maybeOfferPlanImplementation(response);
  }

  private async handleGoalCommand(command: GoalCommand): Promise<void> {
    if (!this.threadId) return;
    if (command.kind === "clear") {
      this.cancelNextGoalTurn = true;
      const result = await this.rpc.request<{ cleared?: boolean }>(
        APP_SERVER_METHODS.THREAD_GOAL_CLEAR,
        { threadId: this.threadId },
      );
      await this.emitGoalState(null);
      await this.cancelRunningGoalTurn();
      this.broadcastAgentText(
        result.cleared ? "Goal cleared." : "No goal was set.",
      );
      return;
    }

    if (command.kind === "get") {
      const result = await this.rpc.request<{ goal?: ThreadGoal | null }>(
        APP_SERVER_METHODS.THREAD_GOAL_GET,
        { threadId: this.threadId },
      );
      this.broadcastAgentText(
        result.goal
          ? `Goal ${result.goal.status}: ${result.goal.objective}`
          : "No goal set. Usage: `/goal <objective>`",
      );
      return;
    }

    if (command.kind === "pause") {
      this.cancelNextGoalTurn = true;
    }
    const params =
      command.kind === "set"
        ? { threadId: this.threadId, objective: command.objective }
        : {
            threadId: this.threadId,
            status: command.kind === "pause" ? "paused" : "active",
          };
    const result = await this.rpc.request<{ goal: ThreadGoal }>(
      APP_SERVER_METHODS.THREAD_GOAL_SET,
      params,
    );
    await this.emitGoalState(result.goal);
    if (command.kind === "pause") {
      await this.cancelRunningGoalTurn();
    }
    const prefix =
      command.kind === "set"
        ? "Goal set"
        : command.kind === "pause"
          ? "Goal paused"
          : "Goal resumed";
    this.broadcastAgentText(`${prefix}: ${result.goal.objective}`);
  }

  private async restoreGoal(goal: NativeGoalState): Promise<void> {
    if (!this.threadId) return;
    const result = await this.rpc.request<{ goal: ThreadGoal }>(
      APP_SERVER_METHODS.THREAD_GOAL_SET,
      {
        threadId: this.threadId,
        objective: goal.objective,
        status: goal.status,
      },
    );
    await this.emitGoalState(result.goal);
  }

  private async emitGoalState(goal: NativeGoalState | null): Promise<void> {
    await this.client
      .extNotification(POSTHOG_NOTIFICATIONS.CODEX_GOAL, { goal })
      .catch((error) =>
        this.logger.warn("Failed to persist Codex goal state", error),
      );
  }

  private async cancelRunningGoalTurn(): Promise<void> {
    if (this.turns.isRunning) {
      this.cancelNextGoalTurn = false;
      await this.interrupt();
      return;
    }
    if (this.nativeGoalTurnId) {
      await this.interruptNativeGoalTurn(this.nativeGoalTurnId);
    }
  }

  private interruptQueuedGoalTurn(turnId: string | undefined): void {
    if (!this.cancelNextGoalTurn || !this.threadId || !turnId) return;
    void this.interruptNativeGoalTurn(turnId);
  }

  private async interruptNativeGoalTurn(turnId: string): Promise<void> {
    if (!this.threadId) return;
    await this.rpc
      .request(APP_SERVER_METHODS.TURN_INTERRUPT, {
        threadId: this.threadId,
        turnId,
      })
      .then(() => {
        this.cancelNextGoalTurn = false;
        if (this.nativeGoalTurnId === turnId) {
          this.nativeGoalTurnId = undefined;
        }
      })
      .catch((error) =>
        this.logger.warn("Native goal turn interrupt failed", error),
      );
  }

  /** Start one codex turn and await its completion. */
  private async runTurn(input: CodexUserInput[]): Promise<PromptResponse> {
    this.lastAgentMessage = "";
    this.resetUsage();
    this.planProposal = undefined;
    this.streamedPlanToolCallId = undefined;
    // A new turn owns the idle boundary; its own completion emits the signal.
    this.deferredTurnComplete = undefined;
    const { completion, turn } = this.turns.begin();
    try {
      const approvalPolicy = this.config.approvalPolicy();
      const sandboxPolicy = this.sandboxPolicyForTurn();
      await this.rpc.request(APP_SERVER_METHODS.TURN_START, {
        threadId: this.threadId,
        input,
        model: this.config.model,
        ...(this.config.effort ? { effort: this.config.effort } : {}),
        // Always request a reasoning summary; the default "auto" can skip it on trivial turns.
        summary: "detailed",
        // Picker preset applied per-turn. codex keeps turn overrides for subsequent turns,
        // so every mode sends its full policy — omitting a field would leave the previous
        // mode's value active (e.g. plan's readOnly sandbox bleeding into auto).
        ...(approvalPolicy ? { approvalPolicy } : {}),
        // Pushed every turn — codex remembers the last mode, so switching back from plan must be explicit.
        collaborationMode: this.config.collaborationModeForTurn(),
        // Skipped on cloud, where a non-danger sandbox re-engages the unavailable
        // linux-sandbox and panics; the enclosing docker/Modal sandbox isolates instead.
        ...(this.environment !== "cloud" && sandboxPolicy
          ? { sandboxPolicy }
          : {}),
        // Constrain the final message to the task schema for parseable structured output.
        ...(this.jsonSchema ? { outputSchema: this.jsonSchema } : {}),
      });
      return await completion;
    } finally {
      this.turns.finishPrompt(turn);
    }
  }

  /**
   * codex plan mode finalizes with a <proposed_plan> item and (by design) never
   * asks "should I proceed?" — the client owns the handoff. Mirror the Claude
   * ExitPlanMode flow: offer to implement; on accept switch the mode and run
   * the implementation turn inside the same prompt() call. Plan feedback loops
   * back into another plan turn, whose revised plan prompts again.
   */
  private async maybeOfferPlanImplementation(
    response: PromptResponse,
  ): Promise<PromptResponse> {
    let result = response;
    try {
      while (
        result.stopReason === "end_turn" &&
        this.config.mode === "plan" &&
        this.planProposal &&
        !this.session.cancelled
      ) {
        const proposal = this.planProposal;
        this.planProposal = undefined;
        const outcome = await this.requestPlanImplementation(proposal);
        // Re-check after the await: a cancel that raced the response wins, so a
        // late accept can never start implementation on a cancelled prompt.
        if (this.session.cancelled) {
          if (outcome.kind === "implement") {
            this.completePlanApprovalToolCall(outcome.toolCallId, "failed");
          }
          result = { ...result, stopReason: "cancelled" };
          break;
        }
        // A picker change while approval was open owns the mode. Never let a
        // stale approval overwrite it with a broader implementation mode.
        if (this.config.mode !== "plan") {
          if (outcome.kind === "implement") {
            this.completePlanApprovalToolCall(outcome.toolCallId, "failed");
          }
          break;
        }
        if (outcome.kind === "implement") {
          this.completePlanApprovalToolCall(outcome.toolCallId, "completed");
          this.config.setOption("mode", outcome.mode);
          this.emitCurrentMode(outcome.mode);
          this.emitConfigOptions();
          result = mergePromptResponses(
            result,
            await this.runFollowUpTurn(IMPLEMENT_PLAN_MESSAGE),
          );
          break;
        }
        if (outcome.kind === "feedback") {
          result = mergePromptResponses(
            result,
            await this.runFollowUpTurn(outcome.feedback),
          );
          continue;
        }
        break;
      }
    } finally {
      await this.flushDeferredTurnComplete(result.stopReason);
    }
    return result;
  }

  /**
   * Emit the idle signal the handoff's plan turn deferred, unless a newer turn
   * took over the boundary (a follow-up turn clears the deferral in runTurn and
   * emits its own completion; a preempting prompt() does the same).
   */
  private async flushDeferredTurnComplete(reason: StopReason): Promise<void> {
    const deferred = this.deferredTurnComplete;
    this.deferredTurnComplete = undefined;
    if (!deferred || this.turns.isPending) return;
    await this.emitTurnCompleteSignal(reason, deferred.usage);
  }

  /** Run an adapter-initiated turn, echoed as a user message like a host prompt. */
  private async runFollowUpTurn(text: string): Promise<PromptResponse> {
    this.broadcastUserInput([{ type: "text", text }]);
    return this.runTurn(toCodexInput([{ type: "text", text }]));
  }

  /**
   * The ExitPlanMode-style approval: a switch_mode tool call (routes the host
   * to its plan-approval UI) whose option ids are codex mode ids. Cancel or a
   * failed prompt stays in plan mode — never silently start implementing.
   */
  private async requestPlanImplementation(proposal: {
    itemId: string;
    text: string;
  }): Promise<
    | {
        kind: "implement";
        mode: "auto" | "full-access";
        toolCallId: string;
      }
    | { kind: "feedback"; feedback: string }
    | { kind: "stay" }
  > {
    const toolCallId = `${proposal.itemId}:implement`;
    const toolCall = this.buildPlanApprovalToolCall(proposal);
    this.emitPlanProposal(toolCall, proposal.text);
    const options = [
      {
        optionId: "auto",
        name: 'Yes, and use "auto" mode',
        kind: "allow_always" as const,
      },
      ...(ALLOW_BYPASS
        ? [
            {
              optionId: "full-access",
              name: "Yes, and auto-approve everything",
              kind: "allow_always" as const,
            },
          ]
        : []),
      {
        optionId: "reject_with_feedback",
        name: "No, and tell Codex what to do differently",
        kind: "reject_once" as const,
        _meta: { customInput: true },
      },
    ];
    // Accept only what was offered: a stale or malformed response must not
    // select a mode that was hidden from the approval UI.
    const offered = new Set(options.map((o) => o.optionId));
    const permission = this.client
      .requestPermission({
        sessionId: this.sessionId,
        toolCall,
        options,
      } as unknown as Parameters<AgentSideConnection["requestPermission"]>[0])
      .then(
        (res: RequestPermissionResponse) => ({ failed: false as const, res }),
        (err: unknown) => ({ failed: true as const, err }),
      );
    // Race against cancellation so cancel/close (or a preempting prompt) settles
    // the handoff instead of leaving prompt() pending on UI that may never answer.
    const cancelled = new Promise<undefined>((resolve) => {
      this.planHandoffCancel = () => resolve(undefined);
    });
    const settled = await Promise.race([permission, cancelled]);
    this.planHandoffCancel = undefined;
    if (!settled) {
      this.completePlanApprovalToolCall(toolCallId, "failed");
      return { kind: "stay" };
    }
    if (settled.failed) {
      this.completePlanApprovalToolCall(toolCallId, "failed");
      this.logger.warn("plan implementation prompt failed; staying in plan", {
        error: String(settled.err),
      });
      // Without this the user sees nothing and Plan mode just sits there.
      this.broadcastAgentText(
        'The plan approval prompt could not be shown. Still in Plan mode — switch the mode to Auto and send "Implement the plan." to proceed.',
      );
      return { kind: "stay" };
    }
    const response = settled.res;
    if (this.session.cancelled || response.outcome.outcome !== "selected") {
      this.completePlanApprovalToolCall(toolCallId, "failed");
      return { kind: "stay" };
    }
    const optionId = response.outcome.optionId;
    if (!offered.has(optionId)) {
      this.completePlanApprovalToolCall(toolCallId, "failed");
      return { kind: "stay" };
    }
    if (optionId === "auto") {
      return { kind: "implement", mode: "auto", toolCallId };
    }
    // Double-gated: only ever offered under ALLOW_BYPASS, and re-checked here.
    if (optionId === "full-access" && ALLOW_BYPASS) {
      return { kind: "implement", mode: "full-access", toolCallId };
    }
    if (optionId === "reject_with_feedback") {
      const feedback = (response as { _meta?: { customInput?: unknown } })._meta
        ?.customInput;
      if (typeof feedback === "string" && feedback.trim()) {
        this.completePlanApprovalToolCall(toolCallId, "failed");
        return { kind: "feedback", feedback: feedback.trim() };
      }
    }
    this.completePlanApprovalToolCall(toolCallId, "failed");
    return { kind: "stay" };
  }

  private buildPlanApprovalToolCall(proposal: {
    itemId: string;
    text: string;
  }): {
    toolCallId: string;
    title: string;
    kind: "switch_mode";
    content: Array<{
      type: "content";
      content: { type: "text"; text: string };
    }>;
    rawInput: { plan: string };
  } {
    return {
      toolCallId: `${proposal.itemId}:implement`,
      title: "Ready to code?",
      kind: "switch_mode",
      content: [
        {
          type: "content",
          content: { type: "text", text: proposal.text },
        },
      ],
      rawInput: { plan: proposal.text },
    };
  }

  private emitPlanProposal(
    toolCall: ReturnType<CodexAppServerAgent["buildPlanApprovalToolCall"]>,
    text: string,
  ): void {
    if (this.streamedPlanToolCallId === toolCall.toolCallId) {
      this.emitPlanApprovalToolCall({
        sessionUpdate: "tool_call_update",
        toolCallId: toolCall.toolCallId,
        status: "in_progress",
        content: [{ type: "content", content: { type: "text", text } }],
        rawInput: { plan: text },
      });
      return;
    }
    this.streamedPlanToolCallId = toolCall.toolCallId;
    this.emitPlanApprovalToolCall({
      sessionUpdate: "tool_call",
      ...toolCall,
      status: "in_progress",
    });
  }

  private completePlanApprovalToolCall(
    toolCallId: string,
    status: "completed" | "failed",
  ): void {
    this.emitPlanApprovalToolCall({
      sessionUpdate: "tool_call_update",
      toolCallId,
      status,
    });
  }

  private emitPlanApprovalToolCall(update: Record<string, unknown>): void {
    const notification = {
      sessionId: this.sessionId,
      update,
    } as unknown as Parameters<AgentSideConnection["sessionUpdate"]>[0];
    this.appendPlanApprovalNotification(notification);
    void this.client.sessionUpdate(notification).catch((error) => {
      this.logger.warn("Failed to emit plan approval tool call update", {
        error: String(error),
        sessionUpdate: update.sessionUpdate,
        toolCallId: update.toolCallId,
      });
    });
  }

  private appendPlanApprovalNotification(
    notification: Parameters<AgentSideConnection["sessionUpdate"]>[0],
  ): void {
    const update = notification.update as Record<string, unknown>;
    if (
      update.sessionUpdate === "tool_call_update" &&
      update.status === "in_progress" &&
      typeof update.toolCallId === "string"
    ) {
      for (
        let index = this.session.notificationHistory.length - 1;
        index >= 0;
        index--
      ) {
        const previous = this.session.notificationHistory[index] as unknown as {
          update?: Record<string, unknown>;
        };
        if (
          previous.update?.sessionUpdate === "tool_call_update" &&
          previous.update.status === "in_progress" &&
          previous.update.toolCallId === update.toolCallId
        ) {
          this.session.notificationHistory[index] = notification;
          return;
        }
      }
    }
    this.appendNotification(this.sessionId, notification);
  }

  /** Emit a plain agent message (user-facing status the model didn't produce). */
  private broadcastAgentText(text: string): void {
    if (!this.sessionId) return;
    void this.client
      .sessionUpdate({
        sessionId: this.sessionId,
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text },
        },
      })
      .catch(() => undefined);
  }

  /** The mode's sandbox with the session's extra writable roots folded into workspaceWrite. */
  private sandboxPolicyForTurn(): CodexSandboxPolicy | undefined {
    const policy = this.config.sandboxPolicy();
    if (
      policy?.type === "workspaceWrite" &&
      this.additionalDirectories?.length
    ) {
      const writableRoots = [
        this.workspaceDirectory,
        ...this.additionalDirectories,
      ].filter((root): root is string => !!root);
      if (writableRoots.length) {
        return { ...policy, writableRoots: [...new Set(writableRoots)] };
      }
    }
    return policy;
  }

  /** Echo each user prompt block (text + image, so an image-only turn still renders) for the host log/UI. */
  private broadcastUserInput(prompt: PromptRequest["prompt"]): void {
    if (!this.sessionId) return;
    for (const block of prompt) {
      if (block.type !== "text" && block.type !== "image") continue;
      void this.client
        .sessionUpdate({
          sessionId: this.sessionId,
          update: {
            sessionUpdate: "user_message_chunk",
            content: block,
          },
        })
        .catch(() => undefined);
    }
  }

  private resetUsage(): void {
    this.usage.resetForTurn();
  }

  protected async interrupt(): Promise<void> {
    // Settle a pending plan-approval race first so prompt() returns instead of
    // waiting on approval UI that may never answer after a cancel.
    this.planHandoffCancel?.();
    // Stop the server, then finalize through the shared path so a cancelled turn still emits
    // the cloud idle signal (finalizeTurn claims idempotently). turn/interrupt requires BOTH
    // threadId and turnId (else -32600); skip the RPC when no turn started.
    const turnId = this.turns.markInterrupted();
    if (this.threadId && turnId) {
      await this.rpc
        .request(APP_SERVER_METHODS.TURN_INTERRUPT, {
          threadId: this.threadId,
          turnId,
        })
        .catch((err) => this.logger.warn("turn/interrupt failed", err));
    }
    await this.finalizeTurn("cancelled");
  }

  async closeSession(): Promise<void> {
    this.commandOutputs.clear();
    this.subagentParents.clear();
    this.pendingSubagentNotifications.clear();
    this.nativeGoalTurnId = undefined;
    this.session.abortController.abort();
    this.session.cancelled = true;
    this.planHandoffCancel?.();
    this.turns.close("cancelled");
    this.session.settingsManager.dispose();
    // Close the transport BEFORE kill() destroys the stdio streams (else close() blocks on
    // an ack that never arrives). Bounded so cleanup can't hang the caller.
    await Promise.race([
      this.rpc.close().catch(() => undefined),
      new Promise<void>((resolve) => setTimeout(resolve, 2000)),
    ]);
    this.proc?.kill();
  }

  private handleNotification(method: string, params: unknown): void {
    const notificationThreadId = readNotificationThreadId(params);
    const isMainThread =
      !notificationThreadId || notificationThreadId === this.threadId;
    const relatedSubagentThreadIds = this.captureSubagentRelationship(
      method,
      params,
      notificationThreadId,
    );
    const mappedParams = isMainThread
      ? this.withBufferedCommandOutput(method, params)
      : params;

    if (this.sessionId && !this.session.cancelled) {
      const notification = mapAppServerNotification(
        this.sessionId,
        method,
        mappedParams,
      );
      const visibleNotification = isMainThread
        ? notification
        : this.mapSubagentNotification(notification, notificationThreadId);
      if (visibleNotification) {
        this.emitSessionNotification(visibleNotification);
      } else if (
        notification &&
        notificationThreadId &&
        isSubagentActivityNotification(notification)
      ) {
        const pending =
          this.pendingSubagentNotifications.get(notificationThreadId) ?? [];
        pending.push(notification);
        this.pendingSubagentNotifications.set(notificationThreadId, pending);
      }
      for (const threadId of relatedSubagentThreadIds) {
        this.flushSubagentNotifications(threadId);
      }
    }

    if (method === APP_SERVER_NOTIFICATIONS.ITEM_STARTED) {
      this.mcp.capture(params);
    }
    if (method === APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED) {
      this.mcp.release(params);
    }

    if (!isMainThread) return;

    if (method === APP_SERVER_NOTIFICATIONS.TURN_STARTED) {
      // Capture the active turn id (steer precondition / interrupt target).
      const turnId = (params as { turn?: { id?: string } })?.turn?.id;
      if (!this.turns.isPending && turnId) {
        this.nativeGoalTurnId = turnId;
      }
      this.turns.onStarted(turnId);
      this.interruptQueuedGoalTurn(turnId);
    }

    // codex auto-compaction surfaces as a contextCompaction item: item/started → in progress,
    // item/completed → boundary (codex emits no separate thread/compacted; that's a guarded
    // fallback). compactionActive dedupes to one boundary per compaction.
    const isCompactionItem =
      (params as { item?: { type?: string } })?.item?.type ===
      "contextCompaction";
    if (
      method === APP_SERVER_NOTIFICATIONS.ITEM_STARTED &&
      isCompactionItem &&
      !this.compactionActive
    ) {
      this.compactionActive = true;
      this.emitCompactionStarted();
    }
    if (
      this.compactionActive &&
      ((method === APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED &&
        isCompactionItem) ||
        method === APP_SERVER_NOTIFICATIONS.CONTEXT_COMPACTED)
    ) {
      this.compactionActive = false;
      this.emitCompactionBoundary();
    }

    if (method === APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED) {
      this.captureAgentMessage(params);
      this.capturePlanProposal(params);
    }
    if (method === APP_SERVER_NOTIFICATIONS.PLAN_DELTA) {
      this.captureStreamedPlanProposal(params);
    }

    if (method === APP_SERVER_NOTIFICATIONS.TOKEN_USAGE_UPDATED) {
      this.emitUsageExtNotification(params);
    }

    if (method === APP_SERVER_NOTIFICATIONS.TURN_COMPLETED) {
      this.commandOutputs.clear();
      const turn = (params as { turn?: { id?: string; status?: string } })
        ?.turn;
      if (turn?.id === this.nativeGoalTurnId) {
        this.nativeGoalTurnId = undefined;
      }
      // Drop the late completion of an already-interrupted turn (else it cancels the follow-up).
      if (this.turns.shouldDropCompletion(turn?.id)) return;
      void this.finalizeTurn(mapTurnStopReason(turn?.status));
    }

    if (method === APP_SERVER_NOTIFICATIONS.MCP_STARTUP_STATUS) {
      const startup = params as {
        name?: string;
        status?: string;
        error?: string | null;
      };
      if (startup?.status === "failed") {
        this.logger.warn("MCP server failed to start; its tools are absent", {
          server: startup.name,
          error: startup.error,
        });
      }
    }

    if (method === APP_SERVER_NOTIFICATIONS.ERROR) {
      // A non-retried fatal error: resolve the turn so prompt() returns rather than hangs.
      const { willRetry, error } = (params ?? {}) as {
        willRetry?: boolean;
        error?: { message?: string };
      };
      if (willRetry === false) {
        this.logger.warn("codex app-server fatal error notification", {
          params,
        });
        const message = error?.message ?? "";
        // A gateway billing denial rejects the prompt so the host classifies
        // it and shows the upgrade gate. It must be a RequestError: a plain
        // Error serializes to a bare "Internal error" at the ACP boundary,
        // which the host reads as fatal and answers with a respawn loop.
        if (classifyGatewayLimitError(message) !== null) {
          if (this.compactionActive) {
            this.compactionActive = false;
            this.emitCompactionBoundary();
          }
          this.turns.fail(RequestError.internalError(undefined, message));
          return;
        }
        if (
          message.includes("413") ||
          message.toLowerCase().includes("request body too large")
        ) {
          this.turns.fail(
            RequestError.internalError(
              undefined,
              "This conversation is too large to continue. Start a new task and carry over a text summary instead of image or tool output.",
            ),
          );
          return;
        }
        void this.finalizeTurn("refusal");
      }
    }
  }

  private captureSubagentRelationship(
    method: string,
    params: unknown,
    senderThreadId: string | undefined,
  ): string[] {
    if (
      method !== APP_SERVER_NOTIFICATIONS.ITEM_STARTED &&
      method !== APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED
    ) {
      return [];
    }
    const item = (params as { item?: AppServerItem })?.item;
    return this.captureSubagentRelationshipItem(item, senderThreadId);
  }

  private restoreSubagentRelationships(
    thread: AppServerThread | undefined,
  ): void {
    for (const turn of thread?.turns ?? []) {
      for (const item of turn.items ?? []) {
        this.captureSubagentRelationshipItem(item, item.senderThreadId);
      }
    }
  }

  private captureSubagentRelationshipItem(
    item: AppServerItem | undefined,
    senderThreadId: string | undefined,
  ): string[] {
    if (
      item?.type !== "collabAgentToolCall" ||
      (item.tool !== "spawnAgent" &&
        item.tool !== "resumeAgent" &&
        item.tool !== "sendInput") ||
      !item.id ||
      !item.receiverThreadIds?.length
    ) {
      return [];
    }
    const parentToolCallId =
      senderThreadId && senderThreadId !== this.threadId
        ? subagentToolCallId(senderThreadId, item.id)
        : item.id;
    for (const receiverThreadId of item.receiverThreadIds) {
      this.subagentParents.set(receiverThreadId, parentToolCallId);
    }
    return item.receiverThreadIds;
  }

  private emitSessionNotification(notification: SessionNotification): void {
    if (!this.sessionId) return;
    void this.client
      .sessionUpdate(notification)
      .catch((err) => this.logger.warn("sessionUpdate failed", err));
    this.appendNotification(this.sessionId, notification);
  }

  private flushSubagentNotifications(threadId: string): void {
    const pending = this.pendingSubagentNotifications.get(threadId);
    if (!pending) return;
    this.pendingSubagentNotifications.delete(threadId);
    for (const notification of pending) {
      const visibleNotification = this.mapSubagentNotification(
        notification,
        threadId,
      );
      if (visibleNotification) {
        this.emitSessionNotification(visibleNotification);
      }
    }
  }

  private mapSubagentNotification(
    notification: SessionNotification | null,
    threadId: string | undefined,
  ): SessionNotification | null {
    if (!notification || !threadId) return null;
    const parentToolCallId = this.subagentParents.get(threadId);
    if (!parentToolCallId) return null;
    if (!isSubagentActivityNotification(notification)) return null;
    const update = notification.update;
    const toolCallId = update.toolCallId
      ? subagentToolCallId(threadId, update.toolCallId)
      : undefined;
    if (update.sessionUpdate === "tool_call_update") {
      return {
        ...notification,
        update: { ...update, ...(toolCallId ? { toolCallId } : {}) },
      } as SessionNotification;
    }
    const existingPosthog = (update._meta?.posthog ?? {}) as Record<
      string,
      unknown
    >;
    return {
      ...notification,
      update: {
        ...update,
        ...(toolCallId ? { toolCallId } : {}),
        _meta: {
          ...update._meta,
          posthog: {
            toolName:
              typeof existingPosthog.toolName === "string"
                ? existingPosthog.toolName
                : "subagent_activity",
            ...existingPosthog,
            parentToolCallId,
          },
        },
      },
    } as SessionNotification;
  }

  private withBufferedCommandOutput(method: string, params: unknown): unknown {
    if (!params || typeof params !== "object") {
      return params;
    }
    const value = params as {
      itemId?: unknown;
      delta?: unknown;
      item?: Record<string, unknown>;
    };

    if (method === APP_SERVER_NOTIFICATIONS.COMMAND_OUTPUT_DELTA) {
      if (typeof value.itemId === "string" && typeof value.delta === "string") {
        this.commandOutputs.set(
          value.itemId,
          `${this.commandOutputs.get(value.itemId) ?? ""}${value.delta}`,
        );
      }
      return params;
    }

    if (method !== APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED) {
      return params;
    }

    const itemId = value.item?.id;
    if (typeof itemId !== "string") {
      return params;
    }

    const output = this.commandOutputs.get(itemId);
    this.commandOutputs.delete(itemId);
    if (
      value.item?.type !== "commandExecution" ||
      value.item.aggregatedOutput != null ||
      !output
    ) {
      return params;
    }

    return {
      ...value,
      item: { ...value.item, aggregatedOutput: output },
    };
  }

  /** Track the latest assistant message so the final one feeds structured output. */
  private captureAgentMessage(params: unknown): void {
    const item = (params as { item?: { type?: string; text?: string } })?.item;
    if (item?.type === "agentMessage" && typeof item.text === "string") {
      this.lastAgentMessage = item.text;
    }
  }

  /** Remember the turn's completed plan item (codex plan mode's authoritative <proposed_plan>). */
  private capturePlanProposal(params: unknown): void {
    const item = (
      params as { item?: { type?: string; id?: string; text?: string } }
    )?.item;
    if (item?.type === "plan" && typeof item.text === "string" && item.text) {
      this.planProposal = {
        itemId: item.id ?? "codex-plan",
        text: item.text.slice(0, MAX_PLAN_PROPOSAL_CHARS),
      };
      if (this.config.mode === "plan" && this.streamedPlanToolCallId) {
        this.emitPlanProposal(
          this.buildPlanApprovalToolCall(this.planProposal),
          this.planProposal.text,
        );
      }
    }
  }

  /** Accumulate the proposal stream used by codex builds that emit no completed plan item. */
  private captureStreamedPlanProposal(params: unknown): void {
    const { itemId, delta } = params as {
      itemId?: unknown;
      delta?: unknown;
    };
    if (typeof delta !== "string" || !delta) return;
    const proposalId =
      typeof itemId === "string" && itemId
        ? itemId
        : (this.planProposal?.itemId ?? "codex-plan");
    const previousText =
      this.planProposal?.itemId === proposalId ? this.planProposal.text : "";
    const remainingChars = MAX_PLAN_PROPOSAL_CHARS - previousText.length;
    if (remainingChars <= 0) return;
    this.planProposal = {
      itemId: proposalId,
      text: previousText + delta.slice(0, remainingChars),
    };
    if (this.config.mode === "plan") {
      this.emitPlanProposal(
        this.buildPlanApprovalToolCall(this.planProposal),
        this.planProposal.text,
      );
    }
  }

  /** Compaction started: emit `_posthog/status` so the host sets `isCompacting` (gates steer/queue). */
  private emitCompactionStarted(): void {
    if (!this.sessionId) return;
    void this.client
      .extNotification(POSTHOG_NOTIFICATIONS.STATUS, {
        sessionId: this.sessionId,
        status: "compacting",
      })
      .catch(() => undefined);
  }

  /** Compaction finished: emit `_posthog/compact_boundary` (host clears isCompacting) + a transcript marker. */
  private emitCompactionBoundary(): void {
    if (!this.sessionId) return;
    void this.client
      .extNotification(POSTHOG_NOTIFICATIONS.COMPACT_BOUNDARY, {
        sessionId: this.sessionId,
      })
      .catch(() => undefined);
    void this.client
      .sessionUpdate({
        sessionId: this.sessionId,
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: "\n\nContext compacted." },
        },
      })
      .catch(() => undefined);
  }

  /** Emit `_posthog/usage_update` so the host's token/cost UI fills. */
  private emitUsageExtNotification(params: unknown): void {
    if (!this.sessionId) return;
    const update = this.usage.ingest(params);
    if (!update) return;
    void this.client
      .extNotification(POSTHOG_NOTIFICATIONS.USAGE_UPDATE, {
        sessionId: this.sessionId,
        ...update,
      })
      .catch((err) => this.logger.warn("usage extNotification failed", err));
  }

  /** Deliver structured output (parsed from the final message) before resolving the turn. */
  private async finalizeTurn(reason: StopReason): Promise<void> {
    // Idempotent: claim synchronously (before any await) so a second finalize (e.g. an
    // error racing turn/completed) is a no-op and callbacks don't double-fire.
    const pending = this.turns.claim();
    if (!pending) return;
    // If the turn dies mid-compaction the boundary never fires, leaving isCompacting stuck
    // true (silently queuing later messages). Recover here.
    if (this.compactionActive) {
      this.compactionActive = false;
      this.emitCompactionBoundary();
    }
    const message = this.lastAgentMessage;
    // Per-turn usage is codex's own `tokenUsage.last` (not a reconstructed delta).
    const usage = this.usage.perTurnUsage();
    const contextUsed = this.usage.contextTokens();

    // Deliver structured output only on a clean end_turn — a cancelled/refused turn records nothing.
    if (
      reason === "end_turn" &&
      this.jsonSchema &&
      this.onStructuredOutput &&
      message
    ) {
      const parsed = parseStructuredOutput(message);
      if (parsed) {
        try {
          await this.onStructuredOutput(parsed);
        } catch (err) {
          this.logger.warn("onStructuredOutput callback threw", { error: err });
        }
      } else {
        this.logger.warn(
          "Could not parse structured output from final message",
          {
            preview: message.slice(0, 200),
          },
        );
      }
    }
    if (this.willOfferPlanHandoff(reason)) {
      // Defer the canonical idle signal: the handoff (and a possible implementation
      // turn) keeps this prompt busy, and the cloud host treats turn_complete as
      // idle — emitting it now would flush queued prompts into the handoff.
      this.deferredTurnComplete = { usage };
      await this.emitUsageBreakdown(contextUsed);
    } else {
      await this.emitTurnCompleteSignal(reason, usage);
      await this.emitUsageBreakdown(contextUsed);
    }
    pending.resolve({
      stopReason: reason,
      ...(usage ? { usage } : {}),
    });
  }

  /** Whether maybeOfferPlanImplementation will run for a turn that ended this way. */
  private willOfferPlanHandoff(reason: StopReason): boolean {
    return (
      reason === "end_turn" &&
      this.config.mode === "plan" &&
      !!this.planProposal &&
      !this.session.cancelled
    );
  }

  /** Emit the cloud idle signal `_posthog/turn_complete` (only with a taskRunId). */
  private async emitTurnCompleteSignal(
    reason: StopReason,
    usage: PromptResponse["usage"],
  ): Promise<void> {
    if (!this.sessionId || !this.taskRunId) return;
    await this.client
      .extNotification(
        POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
        buildTurnCompleteParams(
          this.sessionId,
          reason,
          usage,
        ) as unknown as Record<string, unknown>,
      )
      .catch((err) =>
        this.logger.warn("turn_complete extNotification failed", err),
      );
  }

  /** Emit the `_posthog/usage_update` context breakdown for the host's token UI. */
  private async emitUsageBreakdown(
    contextUsed: number | undefined,
  ): Promise<void> {
    if (!this.sessionId || contextUsed === undefined) return;
    await this.client
      .extNotification(
        POSTHOG_NOTIFICATIONS.USAGE_UPDATE,
        buildUsageBreakdownParams(
          this.sessionId,
          this.usage.baselineBreakdown,
          contextUsed,
        ) as unknown as Record<string, unknown>,
      )
      .catch((err) =>
        this.logger.warn("usage breakdown extNotification failed", err),
      );
  }

  private handleServerClosed(): void {
    this.turns.fail(
      new Error("codex app-server exited before the turn completed"),
    );
  }

  /**
   * Sub-tool policy for a gated PostHog exec call. Codex's `approval_mode:
   * "prompt"` gates the whole exec tool, so this is where the configured regex
   * actually filters: non-matching sub-tools never prompt, and matching ones
   * stay hands-off in local auto/full-access modes (parity with the Claude
   * adapter's `!cloudMode && (auto || bypassPermissions)` branch). Cloud
   * sessions always relay matching sub-tools so AgentServer routes them by the
   * run's effective mode.
   */
  private shouldAutoAcceptPostHogExec(mcp: {
    server: string;
    tool: string;
    args: unknown;
  }): boolean {
    if (!isPostHogExecDescriptor({ server: mcp.server, tool: mcp.tool })) {
      return false;
    }
    const subTool = extractPostHogSubTool(mcp.args);
    if (
      !subTool ||
      !matchesPostHogExecPermission(subTool, this.posthogExecPermissionRegex)
    ) {
      return true;
    }
    return (
      this.environment !== "cloud" &&
      (this.config.mode === "auto" || this.config.mode === "full-access")
    );
  }

  /**
   * Server-initiated requests. Simple approvals resolve to a `{ decision }` envelope (a bare
   * string is rejected); richer ones (AskUserQuestion / permission profile / elicitation) go
   * to `handleServerRequest`. Whatever we return is sent back as the JSON-RPC result.
   */
  private async handleApproval(
    method: string,
    params: unknown,
  ): Promise<unknown> {
    const richer = await handleServerRequest(method, params, this.client, {
      sessionId: this.sessionId,
      logger: this.logger,
      resolveMcpToolCall: (serverName) => this.mcp.byServer(serverName),
      shouldAutoAcceptMcpToolCall: (mcp) =>
        this.shouldAutoAcceptPostHogExec(mcp),
    });
    if (richer.handled) {
      return richer.response;
    }
    if (
      method !== APP_SERVER_REQUESTS.COMMAND_APPROVAL &&
      method !== APP_SERVER_REQUESTS.FILE_CHANGE_APPROVAL
    ) {
      this.logger.warn("Unrecognized server request; declining", { method });
      return { decision: "decline" };
    }
    const isFileChange = method === APP_SERVER_REQUESTS.FILE_CHANGE_APPROVAL;
    const detail = params as {
      itemId?: string;
      command?: string;
      changes?: AppServerItem["changes"];
      availableDecisions?: unknown[];
    };
    // codex lists the decisions valid for this prompt. An "approve and remember"
    // decision is echoed back verbatim: either the string "acceptForSession" or the
    // acceptWithExecpolicyAmendment object carrying the proposed allowlist amendment.
    const availableDecisions = Array.isArray(detail.availableDecisions)
      ? detail.availableDecisions
      : [];
    const offeredRememberDecision =
      availableDecisions.find(
        (d) =>
          !!d && typeof d === "object" && "acceptWithExecpolicyAmendment" in d,
      ) ?? availableDecisions.find((d) => d === "acceptForSession");
    // File-change approvals normally omit availableDecisions, but codex accepts the
    // session-scoped decision for them. If codex sends an explicit list, honor it.
    const rememberDecision: unknown =
      isFileChange && detail.availableDecisions === undefined
        ? "acceptForSession"
        : offeredRememberDecision;
    // Label the actual scope: an execpolicy amendment persists in the command
    // allowlist; acceptForSession (commands and file changes) lasts one session.
    const rememberLabel =
      typeof rememberDecision === "object"
        ? "Allow similar commands and don't ask again"
        : "Allow for the rest of this session";
    const title =
      detail.command ?? (isFileChange ? "Apply file changes" : "Run command");
    const toolCallId = detail.itemId ?? "codex-approval";
    // Codex has no MCP-specific approval; a known MCP call surfaces the real server/tool/args
    // so the host renders the proper MCP permission (incl. PostHog `exec` unwrapping).
    const mcp = this.mcp.byItemId(detail.itemId);
    if (mcp && this.shouldAutoAcceptPostHogExec(mcp)) {
      return { decision: "accept" };
    }
    // kind + content route plain command/file approvals to Execute/EditPermission (not the fallback).
    const toolCall = mcp
      ? {
          toolCallId,
          title,
          kind: "other" as const,
          rawInput: mcp.args,
          _meta: posthogToolMeta({
            toolName: mcpToolKey({ server: mcp.server, tool: mcp.tool }),
            mcp: { server: mcp.server, tool: mcp.tool },
          }),
        }
      : isFileChange
        ? {
            toolCallId,
            title,
            kind: "edit" as const,
            content: diffContent(detail.changes),
            locations: changePaths(detail.changes).map((path) => ({ path })),
          }
        : {
            toolCallId,
            title,
            kind: "execute" as const,
            content: detail.command
              ? [
                  {
                    type: "content" as const,
                    content: { type: "text" as const, text: detail.command },
                  },
                ]
              : undefined,
          };
    try {
      const response = await this.client.requestPermission({
        sessionId: this.sessionId,
        toolCall,
        options: [
          { optionId: "allow", name: "Allow", kind: "allow_once" },
          ...(rememberDecision
            ? [
                {
                  optionId: "allow_always",
                  name: rememberLabel,
                  kind: "allow_always" as const,
                },
              ]
            : []),
          { optionId: "reject", name: "Reject", kind: "reject_once" },
          {
            optionId: "reject_with_feedback",
            name: "No, and tell Codex what to do differently",
            kind: "reject_once",
            _meta: { customInput: true },
          },
        ],
      });
      if (response.outcome.outcome === "selected") {
        if (response.outcome.optionId === "allow_always" && rememberDecision) {
          // Echo codex's "approve and remember" decision so it applies the proposed amendment.
          return { decision: rememberDecision };
        }
        if (response.outcome.optionId === "allow") {
          return { decision: "accept" };
        }
        if (response.outcome.optionId === "reject_with_feedback") {
          // codex's response has no feedback field, so decline and inject the guidance
          // into the running turn (as its TUI does: Denied + a follow-up message).
          const feedback = (response as { _meta?: { customInput?: unknown } })
            ._meta?.customInput;
          const activeTurnId = this.turns.activeTurnId;
          if (typeof feedback === "string" && feedback.trim() && activeTurnId) {
            void this.rpc
              .request<{ turnId?: string }>(APP_SERVER_METHODS.TURN_STEER, {
                threadId: this.threadId,
                input: toCodexInput([{ type: "text", text: feedback.trim() }]),
                expectedTurnId: activeTurnId,
              })
              // codex rotates the turn id on steer; adopt it or later
              // interrupts/steers target a dead turn.
              .then((res) => this.turns.onSteered(res?.turnId))
              .catch((err) =>
                this.logger.warn("turn/steer (reject feedback) failed", err),
              );
          }
          return { decision: "decline" };
        }
      }
      if (response.outcome.outcome === "cancelled") {
        return { decision: "cancel" };
      }
      return { decision: "decline" };
    } catch (err) {
      this.logger.warn("requestPermission failed; declining", err);
      return { decision: "decline" };
    }
  }
}

// BASELINE_TOKENS from codex-rs protocol.rs — the resident floor we can't attribute per-source.
const CODEX_BASELINE_TOKENS = 12000;

// The implementation kickoff message, matching codex's own TUI plan handoff.
const IMPLEMENT_PLAN_MESSAGE = "Implement the plan.";

/** codex `TurnStatus` → ACP `StopReason`: interrupted → cancel, failed → refusal, else end. */
function mapTurnStopReason(status: string | undefined): StopReason {
  if (status === "interrupted") return "cancelled";
  if (status === "failed") return "refusal";
  return "end_turn";
}

function readNotificationThreadId(params: unknown): string | undefined {
  if (!params || typeof params !== "object") return undefined;
  const threadId = (params as { threadId?: unknown }).threadId;
  return typeof threadId === "string" ? threadId : undefined;
}

function subagentToolCallId(threadId: string, toolCallId: string): string {
  return `subagent:${threadId}:${toolCallId}`;
}

function isSubagentActivityNotification(
  notification: SessionNotification,
): notification is SessionNotification & {
  update: SessionNotification["update"] & {
    _meta?: Record<string, unknown>;
    toolCallId?: string;
  };
} {
  const { sessionUpdate } = notification.update;
  return (
    sessionUpdate === "agent_message_chunk" ||
    sessionUpdate === "agent_thought_chunk" ||
    sessionUpdate === "tool_call" ||
    sessionUpdate === "tool_call_update"
  );
}

/** The codex thread config override map: folds in MCP servers + makes extra workspace roots writable. Undefined when empty. */
function buildThreadConfig(
  mcpServers: ReturnType<typeof toCodexMcpServers>,
  additionalDirectories: string[] | undefined,
): Record<string, unknown> | undefined {
  const config: Record<string, unknown> = {};
  if (mcpServers) {
    config.mcp_servers = mcpServers;
  }
  if (additionalDirectories?.length) {
    config.sandbox_workspace_write = { writable_roots: additionalDirectories };
  }
  return Object.keys(config).length > 0 ? config : undefined;
}

/** Seed the context-breakdown baseline with the resident floor + the host's system prompt. */
function buildBaseline(
  meta: AppServerSessionMeta | undefined,
): ContextBreakdownBaseline {
  const baseline = emptyBaseline();
  baseline.systemPrompt =
    CODEX_BASELINE_TOKENS +
    estimateTokens(flattenSystemPrompt(meta?.systemPrompt));
  return baseline;
}

/** Flatten the host's systemPrompt (`string | { append }`) to a string (else "[object Object]"). */
function flattenSystemPrompt(
  systemPrompt: string | { append?: string } | undefined,
): string | undefined {
  if (typeof systemPrompt === "string") return systemPrompt || undefined;
  if (systemPrompt && typeof systemPrompt.append === "string") {
    return systemPrompt.append || undefined;
  }
  return undefined;
}
