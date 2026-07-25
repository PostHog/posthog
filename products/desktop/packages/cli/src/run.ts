import { randomUUID } from "node:crypto";
import { format } from "node:util";
import {
  ClientSideConnection,
  ndJsonStream,
  type RequestPermissionRequest,
  type SessionNotification,
  type StopReason,
} from "@agentclientprotocol/sdk";
import { Agent } from "@posthog/agent/agent";
import type { OnLogCallback } from "@posthog/agent/types";
import { resolveUnattendedPermissionRequest } from "@posthog/agent/unattended-permission-policy";
import { withTimeout } from "@posthog/shared";
import type { CliOptions } from "./args";
import { createOutputSink, type OutputSink } from "./output";

const STOP_REASON_EXIT_CODES: Partial<Record<StopReason, number>> = {
  end_turn: 0,
  refusal: 2,
  max_tokens: 3,
  max_turn_requests: 3,
};

/** 128 + signal number, the shell convention. */
const EXIT_SIGINT = 130;
const EXIT_SIGTERM = 143;

/** Bounded: a wedged adapter cleanup must never hang the process. */
const CLEANUP_TIMEOUT_MS = 8000;

/**
 * A turn cut short by a signal reports that signal's code whatever the adapter
 * settled on; anything unmapped (including "cancelled" with no signal) is a
 * failure the caller should notice.
 */
export function exitCodeFor(
  stopReason: StopReason,
  interruptedBy?: number,
): number {
  return interruptedBy ?? STOP_REASON_EXIT_CODES[stopReason] ?? 1;
}

/**
 * stdout carries only assistant output, so every diagnostic goes to stderr.
 * Errors during the turn always show (a failed run must say why); everything
 * else needs --debug. Teardown errors are expected noise, the adapter reports
 * the connection it is closing, so they drop to --debug once teardown starts.
 */
function createDiagnostics(debug: boolean) {
  const writeDiagnostic = (message: string) =>
    process.stderr.write(`[posthog-code-cli] ${message}\n`);
  const debugLog = debug ? writeDiagnostic : () => {};
  let tearingDown = false;

  return {
    debugLog,
    markTearingDown: () => {
      tearingDown = true;
    },
    onLog: ((level, scope, message, data) => {
      const line = `${scope} [${level}] ${message}${data === undefined ? "" : ` ${format(data)}`}`;
      if (level === "error" && !tearingDown) {
        writeDiagnostic(line);
      } else {
        debugLog(line);
      }
    }) satisfies OnLogCallback,
  };
}

export type RunOptions = CliOptions & { prompt: string };

/**
 * The subset of ClientSideConnection the turn drives. Structural, so the real
 * connection satisfies it without a cast and a test can supply a stub.
 */
export interface TurnConnection {
  initialize(params: {
    protocolVersion: number;
    clientCapabilities: Record<string, never>;
  }): Promise<unknown>;
  newSession(params: {
    cwd: string;
    mcpServers: never[];
    _meta: Record<string, unknown>;
  }): Promise<{ sessionId: string }>;
  prompt(params: {
    sessionId: string;
    prompt: { type: "text"; text: string }[];
  }): Promise<{ stopReason: StopReason; usage?: unknown }>;
  cancel(params: { sessionId: string }): Promise<void>;
}

export interface TurnHooks {
  debugLog: (message: string) => void;
  markTearingDown: () => void;
  cleanup: () => Promise<void>;
  /** Injectable so a test can drive the no-session signal path. */
  exit?: (code: number) => void;
}

/**
 * Opens a session, runs one turn, and maps the outcome to an exit code. Owns the
 * signal handlers for the turn's lifetime and removes them on the way out.
 */
export async function runTurn(
  conn: TurnConnection,
  options: RunOptions,
  sink: OutputSink,
  hooks: TurnHooks,
): Promise<number> {
  const { debugLog, markTearingDown, cleanup } = hooks;
  const exit = hooks.exit ?? ((code: number) => process.exit(code));

  let sessionId: string | undefined;
  let interruptedBy: number | undefined;
  let settled = false;

  // SIGTERM as well as SIGINT: a supervisor (CI step, cron, container runtime)
  // terminates with SIGTERM, and Node's default disposition for it skips the
  // finally below, leaving the agent's claude subprocess orphaned.
  const onSignal = (exitCode: number) => () => {
    interruptedBy = exitCode;
    const id = sessionId;
    if (!id) {
      // Nothing to cancel yet, so exit directly. Flag teardown first, or the
      // adapter's closing-connection errors print to stderr without --debug.
      markTearingDown();
      void cleanup().then(() => exit(exitCode));
      return;
    }
    // Cancel resolves an in-flight prompt() with stopReason "cancelled"; the
    // normal path then finishes output and exits with this code. A second signal
    // (the handlers are `once`) falls through to Node's default kill.
    const sendCancel = () =>
      void conn.cancel({ sessionId: id }).catch(() => undefined);
    sendCancel();
    // A cancel that lands before the turn activates is discarded, so re-send
    // until the turn settles. See the guard after newSession for the rest.
    const retry = setInterval(() => {
      if (settled) clearInterval(retry);
      else sendCancel();
    }, 500);
    retry.unref();
  };
  const onSigint = onSignal(EXIT_SIGINT);
  const onSigterm = onSignal(EXIT_SIGTERM);
  process.once("SIGINT", onSigint);
  process.once("SIGTERM", onSigterm);

  try {
    await conn.initialize({ protocolVersion: 1, clientCapabilities: {} });
    const session = await conn.newSession({
      cwd: options.cwd,
      mcpServers: [],
      _meta: {
        permissionMode: options.permissionMode,
        ...(options.model ? { model: options.model } : {}),
        ...(options.systemPrompt ? { systemPrompt: options.systemPrompt } : {}),
      },
    });
    sessionId = session.sessionId;
    debugLog(`session ${sessionId} started in ${options.cwd}`);

    // A signal that landed during session setup has nothing to cancel yet and
    // its handler already started teardown, so stop before opening a turn.
    if (interruptedBy) return interruptedBy;

    try {
      const result = await conn.prompt({
        sessionId,
        prompt: [{ type: "text", text: options.prompt }],
      });
      debugLog(`turn finished: ${result.stopReason}`);

      sink.finish({
        stopReason: result.stopReason,
        usage: result.usage as Parameters<OutputSink["finish"]>[0]["usage"],
        sessionId,
      });
      return exitCodeFor(result.stopReason, interruptedBy);
    } finally {
      settled = true;
    }
  } finally {
    markTearingDown();
    process.removeListener("SIGINT", onSigint);
    process.removeListener("SIGTERM", onSigterm);
    await cleanup();
  }
}

export async function run(options: RunOptions): Promise<number> {
  const { debugLog, markTearingDown, onLog } = createDiagnostics(options.debug);

  // No posthog config: gateway resolution is skipped and the agent subprocess
  // inherits ANTHROPIC_* auth from process.env.
  const agent = new Agent({
    debug: options.debug,
    // Safe to opt in here, unlike desktop and cloud: this sink is the operator's
    // own stderr, and nothing persists or transmits it.
    forwardAdapterLogs: true,
    onLog,
  });
  const acp = await agent.run("cli", `cli-${randomUUID()}`, {
    adapter: "claude",
  });

  const sink = createOutputSink(options.output, process.stdout);

  const client = {
    async sessionUpdate(notification: SessionNotification): Promise<void> {
      sink.onSessionUpdate(notification);
    },
    async requestPermission(params: RequestPermissionRequest) {
      const response = resolveUnattendedPermissionRequest(params);
      debugLog(
        `permission "${params.toolCall.title ?? "unknown"}" -> ${JSON.stringify(response.outcome)}`,
      );
      return response;
    },
    // No readTextFile/writeTextFile and empty clientCapabilities below: the
    // adapter runs file tools in-process instead of proxying through the host.
    async extNotification(): Promise<void> {},
  };

  const conn = new ClientSideConnection(
    () => client,
    ndJsonStream(acp.clientStreams.writable, acp.clientStreams.readable),
  );

  return runTurn(conn, options, sink, {
    debugLog,
    markTearingDown,
    cleanup: async () => {
      await withTimeout(
        agent.cleanup().catch(() => undefined),
        CLEANUP_TIMEOUT_MS,
      );
    },
  });
}
