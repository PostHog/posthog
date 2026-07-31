import { randomUUID } from "node:crypto";
import { format } from "node:util";
import {
  ClientSideConnection,
  ndJsonStream,
  type RequestPermissionRequest,
  type SessionNotification,
} from "@agentclientprotocol/sdk";
import { Agent } from "@posthog/agent/agent";
import { withTimeout } from "@posthog/shared";
import type { CliOptions } from "./args";
import { createOutputSink } from "./output";
import { resolvePermissionRequest } from "./permission-policy";

const STOP_REASON_EXIT_CODES: Record<string, number> = {
  end_turn: 0,
  refusal: 2,
  max_tokens: 3,
  max_turn_requests: 3,
};

export type RunOptions = CliOptions & { prompt: string };

export async function run(options: RunOptions): Promise<number> {
  const writeDiagnostic = (message: string) =>
    process.stderr.write(`[posthog-code-cli] ${message}\n`);
  const debugLog = options.debug ? writeDiagnostic : () => {};

  // stdout must carry only assistant output. onLog bypasses the adapter's
  // console logging entirely; errors during the turn always reach stderr (a
  // failed run must say why), everything else only with --debug. Teardown
  // errors are expected noise (the adapter reports the closing connection).
  // No posthog config: gateway resolution is skipped and the agent subprocess
  // inherits ANTHROPIC_* auth from process.env.
  let tearingDown = false;
  const agent = new Agent({
    debug: options.debug,
    onLog: (level, scope, message, data) => {
      const line = `${scope} [${level}] ${message}${data === undefined ? "" : ` ${format(data)}`}`;
      if (level === "error" && !tearingDown) {
        writeDiagnostic(line);
      } else {
        debugLog(line);
      }
    },
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
      const response = resolvePermissionRequest(params);
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

  const cleanup = async () => {
    // Bounded: a wedged adapter cleanup must never hang the process.
    await withTimeout(
      agent.cleanup().catch(() => undefined),
      8000,
    );
  };

  let sessionId: string | undefined;
  let interrupted = false;
  const onSigint = () => {
    interrupted = true;
    if (sessionId) {
      // Cancel resolves the in-flight prompt() with stopReason "cancelled";
      // the normal path then finishes output and exits 130. A second Ctrl-C
      // (the handler is `once`) falls through to Node's default kill.
      void conn.cancel({ sessionId }).catch(() => undefined);
    } else {
      // Nothing to cancel yet — exit directly.
      void cleanup().then(() => process.exit(130));
    }
  };
  process.once("SIGINT", onSigint);

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

    const result = await conn.prompt({
      sessionId,
      prompt: [{ type: "text", text: options.prompt }],
    });
    debugLog(`turn finished: ${result.stopReason}`);

    sink.finish({
      stopReason: result.stopReason,
      usage: result.usage,
      sessionId,
    });
    if (interrupted) return 130;
    return STOP_REASON_EXIT_CODES[result.stopReason] ?? 1;
  } finally {
    tearingDown = true;
    process.removeListener("SIGINT", onSigint);
    await cleanup();
  }
}
