import { randomUUID } from "node:crypto";
import { format } from "node:util";
import {
  ClientSideConnection,
  ndJsonStream,
  type RequestPermissionRequest,
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
  const debugLog = options.debug
    ? (message: string) =>
        process.stderr.write(`[posthog-code-cli] ${message}\n`)
    : () => {};

  // stdout must carry only assistant output. onLog bypasses the adapter's
  // console logging entirely, routing diagnostics to stderr behind --debug.
  // No posthog config: gateway resolution is skipped and the agent subprocess
  // inherits ANTHROPIC_* auth from process.env.
  const agent = new Agent({
    debug: options.debug,
    onLog: (level, scope, message, data) =>
      debugLog(
        `${scope} [${level}] ${message}${data === undefined ? "" : ` ${format(data)}`}`,
      ),
  });
  const acp = await agent.run("cli", `cli-${randomUUID()}`, {
    adapter: "claude",
  });

  const sink = createOutputSink(options.output, process.stdout);

  const client = {
    async sessionUpdate(notification: unknown): Promise<void> {
      sink.onSessionUpdate(notification);
    },
    async requestPermission(params: RequestPermissionRequest) {
      const response = resolvePermissionRequest(params);
      debugLog(
        `permission "${params.toolCall?.title ?? "unknown"}" -> ${JSON.stringify(response.outcome)}`,
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
  const onSigint = () => {
    void (async () => {
      if (sessionId) {
        await conn.cancel({ sessionId }).catch(() => undefined);
      }
      await cleanup();
      process.exit(130);
    })();
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
    const stopReason = result.stopReason ?? "unknown";
    debugLog(`turn finished: ${stopReason}`);

    sink.finish({
      stopReason,
      usage: (result as { usage?: unknown }).usage,
      sessionId,
    });
    return STOP_REASON_EXIT_CODES[stopReason] ?? 1;
  } finally {
    process.removeListener("SIGINT", onSigint);
    await cleanup();
  }
}
