import { type ChildProcess, execFileSync, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { delimiter, dirname } from "node:path";
import type { Readable, Writable } from "node:stream";
import { applyContextWikiEnv } from "../../context-wiki";
import type { ContextWikiEnv, ProcessSpawnedCallback } from "../../types";
import { Logger } from "../../utils/logger";

/**
 * Host-facing codex options passed through `createAcpConnection`'s
 * `codexOptions`. The connection layer maps these onto
 * `CodexAppServerProcessOptions` plus the agent-level model settings.
 */
export interface CodexOptions {
  cwd?: string;
  apiBaseUrl?: string;
  apiKey?: string;
  model?: string;
  reasoningEffort?: string;
  /**
   * Static HTTP headers forwarded on every request to the PostHog gateway
   * (the codex equivalent of Claude's `ANTHROPIC_CUSTOM_HEADERS`). Carries the
   * `x-posthog-property-*` attribution headers the gateway lifts onto the
   * `$ai_generation` event (team_id, ai_stage, task metadata).
   */
  httpHeaders?: Record<string, string>;
  /** Guidance appended on top of Codex's base prompt via `developer_instructions`. */
  developerInstructions?: string;
  /**
   * Bundled-binary hint: the native codex binary itself, or any file in the
   * directory that contains it (see `nativeCodexBinaryPath`).
   */
  binaryPath?: string;
  codexHome?: string;
  useMachineAuth?: boolean;
  /** Extra codex `-c key=value` config overrides. */
  configOverrides?: Record<string, string | number>;
  /**
   * Additional writable roots. Currently only honored per-thread via prompt
   * params; accepted here so hosts can pass it uniformly.
   */
  additionalDirectories?: string[];
  logger?: Logger;
  processCallbacks?: ProcessSpawnedCallback;
}

export interface CodexAppServerProcessOptions {
  /** Path to the native `codex` CLI binary (the one that exposes `app-server`). */
  binaryPath: string;
  cwd?: string;
  apiBaseUrl?: string;
  apiKey?: string;
  codexHome?: string;
  useMachineAuth?: boolean;
  /** Guidance appended to Codex's base prompt via `developer_instructions`. */
  developerInstructions?: string;
  /**
   * Static HTTP headers forwarded on every request to the PostHog gateway, set
   * as `model_providers.posthog.http_headers`. Codex equivalent of Claude's
   * `ANTHROPIC_CUSTOM_HEADERS` (see {@link CodexOptions.httpHeaders}).
   */
  httpHeaders?: Record<string, string>;
  /** Extra codex `-c key=value` config overrides (e.g. auto_compact_token_limit). */
  configOverrides?: Record<string, string | number>;
  /** Per-session context wiki mount forwarded to the subprocess env. */
  contextWiki?: ContextWikiEnv;
  logger?: Logger;
  processCallbacks?: ProcessSpawnedCallback;
}

/** Idle time on a gateway SSE stream before codex abandons it and retries, in cloud sandboxes. */
export const SANDBOX_STREAM_IDLE_TIMEOUT_MS = 90_000;

export interface CodexAppServerProcess {
  process: ChildProcess;
  stdin: Writable;
  stdout: Readable;
  kill: () => void;
}

function getUnixProcessTreePids(rootPid: number): number[] | undefined {
  let processTable: string;
  try {
    processTable = execFileSync("ps", ["-ax", "-o", "pid=,ppid="], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
  } catch {
    return undefined;
  }

  const childrenByParent = new Map<number, number[]>();
  for (const line of processTable.split("\n")) {
    const [pidText, parentPidText] = line.trim().split(/\s+/);
    const pid = Number.parseInt(pidText, 10);
    const parentPid = Number.parseInt(parentPidText, 10);
    if (Number.isNaN(pid) || Number.isNaN(parentPid)) continue;
    const children = childrenByParent.get(parentPid) ?? [];
    children.push(pid);
    childrenByParent.set(parentPid, children);
  }

  const processTreePids: number[] = [];
  const visited = new Set<number>();
  const addProcessTree = (pid: number): void => {
    if (visited.has(pid)) return;
    visited.add(pid);
    for (const childPid of childrenByParent.get(pid) ?? []) {
      addProcessTree(childPid);
    }
    processTreePids.push(pid);
  };
  addProcessTree(rootPid);
  return processTreePids;
}

/** Serialize a string map as a TOML basic string (escapes `\` and `"`). */
function tomlBasicString(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/** Render a `Record<string, string>` as a TOML inline table. */
function tomlInlineTable(entries: Record<string, string>): string {
  const pairs = Object.entries(entries).map(
    ([key, value]) => `${tomlBasicString(key)} = ${tomlBasicString(value)}`,
  );
  return `{ ${pairs.join(", ")} }`;
}

export function buildAppServerArgs(
  options: CodexAppServerProcessOptions,
  environment: NodeJS.ProcessEnv = process.env,
): string[] {
  const args: string[] = ["app-server"];

  args.push("-c", "features.remote_models=false");

  // Ambient plugins from the user's config.toml inject MCP servers and
  // session-start hooks into PostHog sessions (e.g. an unauthenticated plugin
  // MCP failing every thread, hooks wedging turns). Threads only get the MCP
  // servers PostHog injects, so disable the plugin system outright.
  args.push("-c", "features.plugins=false");

  // PostHog owns these integrations. Do not run user hooks or send task data
  // to telemetry exporters from the user's Codex config.
  args.push("-c", "mcp_servers={}");
  args.push("-c", "hooks={}");
  args.push("-c", "notify=[]");
  args.push("-c", `otel.exporter="none"`);
  args.push("-c", `otel.metrics_exporter="none"`);
  args.push("-c", `otel.trace_exporter="none"`);
  args.push("-c", "otel.log_user_prompt=false");

  if (options.useMachineAuth) {
    args.push("-c", `model_provider="openai"`);
    args.push("-c", `forced_login_method="chatgpt"`);
    args.push("-c", `history.persistence="none"`);
  } else {
    args.push("-c", `cli_auth_credentials_store="file"`);
    args.push("-c", `mcp_oauth_credentials_store="file"`);
  }

  // OS sandbox gated on platform (= availability): macOS Seatbelt → workspace-write
  // (keeps the sandbox engaged so a per-turn readOnly can tighten it and block
  // edits); linux/windows have no sandbox launcher and would panic, so
  // danger-full-access (the enclosing docker/Modal sandbox isolates instead).
  args.push(
    "-c",
    process.platform === "darwin"
      ? `sandbox_mode="workspace-write"`
      : `sandbox_mode="danger-full-access"`,
  );

  // The host owns approvals (surfaced via approvals.ts → requestPermission). Codex's
  // guardian reviewer is on by default and routes approvals to its dedicated
  // `codex-auto-review` model, which our gateway's posthog_code allowlist doesn't
  // serve — so every review 403s. Default codex's own `user` reviewer; a caller can
  // still override it via configOverrides, which the trailing loop appends last.
  args.push("-c", `approvals_reviewer="user"`);

  // Codex snapshots shell state only for the thread's initial cwd. Cloud tasks
  // can work in additional checkouts, so pin the backend-controlled BASH_ENV
  // path into every tool shell instead of relying on snapshot restoration.
  if (environment.IS_SANDBOX && environment.BASH_ENV) {
    args.push(
      "-c",
      `shell_environment_policy.set.BASH_ENV=${tomlBasicString(environment.BASH_ENV)}`,
    );
  }

  if (options.apiBaseUrl) {
    args.push("-c", `model_provider="posthog"`);
    args.push("-c", `model_providers.posthog.name="PostHog Gateway"`);
    args.push("-c", `model_providers.posthog.base_url="${options.apiBaseUrl}"`);
    args.push("-c", `model_providers.posthog.wire_api="responses"`);
    args.push(
      "-c",
      `model_providers.posthog.env_key="POSTHOG_GATEWAY_API_KEY"`,
    );

    // Attribution + task-metadata headers the gateway lifts onto the captured
    // $ai_generation event. Passed as a single TOML inline table so hyphenated
    // header names (`x-posthog-property-*`) stay quoted rather than becoming
    // bare-key segments of a dotted `-c` path.
    if (options.httpHeaders && Object.keys(options.httpHeaders).length > 0) {
      args.push(
        "-c",
        `model_providers.posthog.http_headers=${tomlInlineTable(options.httpHeaders)}`,
      );
    }

    // Gateway response streams occasionally go silent mid-generation and stay
    // open. Codex only retries once the stream has been idle for
    // stream_idle_timeout_ms (default 300000), so each stall costs a cloud run
    // five minutes of wall clock and sandbox occupancy. A shorter idle timeout
    // bounds that cost; the retry re-issues the request. Cloud-only because a
    // desktop user can see and interrupt a hung turn themselves.
    if (environment.IS_SANDBOX) {
      args.push(
        "-c",
        `model_providers.posthog.stream_idle_timeout_ms=${SANDBOX_STREAM_IDLE_TIMEOUT_MS}`,
      );
    }
  }

  // developer_instructions are set per-thread in thread/start (with the host's
  // task system prompt), not as a spawn-level global default.

  // Numbers/bools go bare; strings are quoted, matching codex's `-c` parser.
  for (const [key, value] of Object.entries(options.configOverrides ?? {})) {
    args.push(
      "-c",
      `${key}=${typeof value === "number" ? value : `"${value}"`}`,
    );
  }

  return args;
}

export function spawnCodexAppServerProcess(
  options: CodexAppServerProcessOptions,
): CodexAppServerProcess {
  const logger =
    options.logger ?? new Logger({ debug: true, prefix: "[CodexAppServer]" });

  if (!existsSync(options.binaryPath)) {
    throw new Error(
      `codex binary not found at ${options.binaryPath}. Run "node apps/code/scripts/download-binaries.mjs" to download it.`,
    );
  }

  const env: NodeJS.ProcessEnv = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ELECTRON_NO_ASAR;
  delete env.POSTHOG_GATEWAY_API_KEY;
  // Codex hands its environment to every shell the exec tools run, so an
  // ambient provider key would be readable by any script the agent executes.
  // Neither auth mode needs them: gateway mode pins model_provider to the
  // PostHog provider (env_key=POSTHOG_GATEWAY_API_KEY), machine auth uses the
  // ChatGPT login state.
  delete env.CODEX_ACCESS_TOKEN;
  delete env.CODEX_API_KEY;
  delete env.OPENAI_API_KEY;
  delete env.OPENAI_API_BASE;
  delete env.OPENAI_BASE_URL;
  if (options.apiKey) {
    env.POSTHOG_GATEWAY_API_KEY = options.apiKey;
  }
  if (options.codexHome) {
    if (!options.useMachineAuth) env.CODEX_HOME = options.codexHome;
    env.CODEX_SQLITE_HOME = options.codexHome;
  }
  applyContextWikiEnv(env, options.contextWiki);
  env.PATH = `${dirname(options.binaryPath)}${delimiter}${env.PATH ?? ""}`;

  const args = buildAppServerArgs(options, env);

  logger.info("Spawning codex app-server process", {
    command: options.binaryPath,
    args,
    cwd: options.cwd,
  });

  const child = spawn(options.binaryPath, args, {
    cwd: options.cwd,
    env,
    stdio: ["pipe", "pipe", "pipe"],
    detached: process.platform !== "win32",
  });

  child.stderr?.on("data", (data: Buffer) => {
    logger.warn("codex app-server stderr:", data.toString());
  });

  child.on("error", (err) => {
    logger.error("codex app-server process error:", err);
  });

  child.on("exit", (code, signal) => {
    logger.info("codex app-server process exited", { code, signal });
    if (child.pid && options.processCallbacks?.onProcessExited) {
      options.processCallbacks.onProcessExited(child.pid);
    }
  });

  if (!child.stdin || !child.stdout) {
    throw new Error(
      "Failed to get stdio streams from codex app-server process",
    );
  }

  if (child.pid && options.processCallbacks?.onProcessSpawned) {
    options.processCallbacks.onProcessSpawned({
      pid: child.pid,
      command: options.binaryPath,
    });
  }

  return {
    process: child,
    stdin: child.stdin,
    stdout: child.stdout,
    kill: () => {
      logger.info("Killing codex app-server process", { pid: child.pid });
      child.stdin?.destroy();
      child.stdout?.destroy();
      child.stderr?.destroy();
      if (process.platform !== "win32" && child.pid) {
        const processTreePids = getUnixProcessTreePids(child.pid);
        if (processTreePids) {
          for (const pid of processTreePids) {
            try {
              process.kill(pid, "SIGTERM");
            } catch {}
          }
          return;
        }
      }
      child.kill("SIGTERM");
    },
  };
}
