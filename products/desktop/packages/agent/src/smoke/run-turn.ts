import { randomUUID } from "node:crypto";
import { promises as fsp, mkdtempSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import {
  type Client,
  ClientSideConnection,
  ndJsonStream,
} from "@agentclientprotocol/sdk";
import type { Adapter } from "@posthog/shared";
import {
  type AcpConnection,
  createAcpConnection,
} from "../adapters/acp-connection";
import type { GatewayEnv } from "../adapters/claude/session/options";
import { codexAuthFromGatewayEnv } from "../server/gateway-env";
import type { Logger } from "../utils/logger";

export interface TurnOutcome {
  stopReason: string | undefined;
  completedToolCalls: number;
  replyHasNonce: boolean;
  reply: string;
}

const PROMPT =
  "Use a tool to read the file nonce.txt, then reply with its contents only.";

export async function runTurn({
  runtime,
  model,
  gatewayEnv,
  timeoutSeconds,
  logger,
}: {
  runtime: Adapter;
  model: string;
  gatewayEnv: GatewayEnv;
  timeoutSeconds: number;
  logger: Logger;
}): Promise<TurnOutcome> {
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), "agent-smoke-")));
  let acp: AcpConnection | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const nonce = randomUUID();
    await fsp.writeFile(join(cwd, "nonce.txt"), `${nonce}\n`);

    let reply = "";
    const completedToolCallIds = new Set<string>();
    const client: Client = {
      async sessionUpdate({ update }) {
        if (
          update.sessionUpdate === "agent_message_chunk" &&
          update.content.type === "text"
        ) {
          reply += update.content.text;
        }
        if (
          (update.sessionUpdate === "tool_call" ||
            update.sessionUpdate === "tool_call_update") &&
          update.status === "completed"
        ) {
          completedToolCallIds.add(update.toolCallId);
        }
      },
      async requestPermission({ options }) {
        const allow =
          options.find(
            (o) => o.kind === "allow_once" || o.kind === "allow_always",
          ) ?? options[0];
        return {
          outcome: {
            outcome: "selected",
            optionId: allow?.optionId ?? "allow",
          },
        };
      },
      async readTextFile({ path }) {
        return { content: await fsp.readFile(resolve(cwd, path), "utf8") };
      },
      async writeTextFile({ path, content }) {
        await fsp.writeFile(resolve(cwd, path), content);
        return {};
      },
      async extNotification() {},
    };

    acp = createAcpConnection({
      adapter: runtime,
      deviceType: "cloud",
      logger,
      claudeGatewayEnv: runtime === "claude" ? gatewayEnv : undefined,
      codexOptions:
        runtime === "codex"
          ? {
              cwd,
              ...codexAuthFromGatewayEnv(gatewayEnv),
              binaryPath: process.env.POSTHOG_CODEX_BINARY_PATH,
              model,
              httpHeaders: gatewayEnv.openaiCustomHeaders,
            }
          : undefined,
    });
    const conn = new ClientSideConnection(
      () => client,
      ndJsonStream(acp.clientStreams.writable, acp.clientStreams.readable),
    );
    let sessionId: string | undefined;
    const turn = (async () => {
      await conn.initialize({ protocolVersion: 1, clientCapabilities: {} });
      const session = await conn.newSession({
        cwd,
        mcpServers: [],
        _meta: {
          environment: "cloud",
          model,
          permissionMode: runtime === "codex" ? "auto" : "bypassPermissions",
        },
      });
      sessionId = session.sessionId;
      return conn.prompt({
        sessionId: session.sessionId,
        prompt: [{ type: "text", text: PROMPT }],
      });
    })();
    turn.catch(() => undefined);
    const { stopReason } = await Promise.race([
      turn,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          if (sessionId) {
            conn.cancel({ sessionId }).catch(() => undefined);
          }
          reject(new Error(`turn timed out after ${timeoutSeconds}s`));
        }, timeoutSeconds * 1000);
      }),
    ]);
    return {
      stopReason,
      completedToolCalls: completedToolCallIds.size,
      replyHasNonce: reply.includes(nonce),
      reply,
    };
  } finally {
    clearTimeout(timer);
    if (acp) {
      await Promise.race([
        acp.cleanup().catch(() => undefined),
        new Promise<void>((r) => setTimeout(r, 8000)),
      ]);
    }
    await fsp.rm(cwd, { recursive: true, force: true });
  }
}
