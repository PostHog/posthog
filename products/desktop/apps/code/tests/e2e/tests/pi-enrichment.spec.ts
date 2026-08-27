import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import path from "node:path";
import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import { expect, test } from "../fixtures/electron";

const HOME_ENVIRONMENT_KEYS = [
  "APPDATA",
  "HOME",
  "LOCALAPPDATA",
  "USERPROFILE",
  "XDG_CONFIG_HOME",
] as const;

function createAnthropicStream(content: "tool" | "text"): string {
  const messageStart = {
    type: "message_start",
    message: {
      id: `msg_${content}`,
      type: "message",
      role: "assistant",
      content: [],
      model: "claude-haiku-4-5",
      stop_reason: null,
      stop_sequence: null,
      usage: { input_tokens: 10, output_tokens: 0 },
    },
  };
  const events =
    content === "tool"
      ? [
          messageStart,
          {
            type: "content_block_start",
            index: 0,
            content_block: {
              type: "tool_use",
              id: "toolu_read_1",
              name: "read",
              input: {},
            },
          },
          {
            type: "content_block_delta",
            index: 0,
            delta: {
              type: "input_json_delta",
              partial_json: JSON.stringify({ path: "example.ts" }),
            },
          },
          { type: "content_block_stop", index: 0 },
          {
            type: "message_delta",
            delta: { stop_reason: "tool_use", stop_sequence: null },
            usage: { output_tokens: 10 },
          },
          { type: "message_stop" },
        ]
      : [
          messageStart,
          {
            type: "content_block_start",
            index: 0,
            content_block: { type: "text", text: "" },
          },
          {
            type: "content_block_delta",
            index: 0,
            delta: { type: "text_delta", text: "Enrichment observed." },
          },
          { type: "content_block_stop", index: 0 },
          {
            type: "message_delta",
            delta: { stop_reason: "end_turn", stop_sequence: null },
            usage: { output_tokens: 5 },
          },
          { type: "message_stop" },
        ];

  return events
    .map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`)
    .join("");
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.from(chunk));
  }

  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function sendJson(response: ServerResponse, data: unknown): void {
  response.writeHead(200, { "Content-Type": "application/json" });
  response.end(JSON.stringify(data));
}

test.describe("Pi enrichment", () => {
  test("enriches a read result through the bundled RPC host", async ({
    electronApp,
  }) => {
    const { e2eHome, resourcesPath } = await electronApp.evaluate(
      async ({ app }) => ({
        e2eHome: process.env.HOME ?? app.getPath("home"),
        resourcesPath: process.resourcesPath,
      }),
    );
    const rpcHostPath = path.join(
      resourcesPath,
      "app.asar.unpacked",
      ".vite",
      "build",
      "rpc-host.js",
    );
    expect(existsSync(rpcHostPath)).toBe(true);

    const workspace = path.join(e2eHome, "enrichment-workspace");
    await mkdir(workspace, { recursive: true });
    await writeFile(
      path.join(workspace, "example.ts"),
      'posthog.capture("checkout_completed");\n',
    );

    let initialModelRequest = "";
    let enrichedModelRequest = "";
    let eventDefinitionRequests = 0;
    let eventStatsRequests = 0;
    const server = createServer(async (request, response) => {
      const url = new URL(request.url ?? "/", "http://127.0.0.1");

      if (request.method === "GET" && url.pathname === "/v1/models") {
        sendJson(response, {
          data: [
            {
              id: "claude-haiku-4-5",
              owned_by: "anthropic",
              context_window: 200000,
              supports_vision: true,
            },
          ],
        });
        return;
      }

      if (request.method === "POST" && url.pathname === "/v1/messages") {
        const body = await readJson(request);
        const serialized = JSON.stringify(body);
        const hasToolResult = serialized.includes('"tool_result"');
        if (hasToolResult) {
          enrichedModelRequest = serialized;
        } else {
          initialModelRequest = serialized;
        }
        response.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
        });
        response.end(createAnthropicStream(hasToolResult ? "text" : "tool"));
        return;
      }

      if (
        request.method === "GET" &&
        url.pathname === "/api/projects/1/event_definitions/"
      ) {
        eventDefinitionRequests += 1;
        sendJson(response, {
          results: [
            {
              id: "event-1",
              name: "checkout_completed",
              tags: ["revenue"],
              last_seen_at: "2026-08-13T12:00:00Z",
              verified: true,
            },
          ],
        });
        return;
      }

      if (
        request.method === "POST" &&
        url.pathname === "/api/projects/1/query/"
      ) {
        eventStatsRequests += 1;
        sendJson(response, {
          results: [["checkout_completed", 321, 87, "2026-08-13T12:00:00Z"]],
        });
        return;
      }

      response.writeHead(404);
      response.end();
    });

    await new Promise<void>((resolveListening) => {
      server.listen(0, "127.0.0.1", resolveListening);
    });
    const address = server.address();
    if (!address || typeof address === "string") {
      throw new Error("Fake PostHog server did not bind a TCP port");
    }

    const previousEnvironment = new Map(
      HOME_ENVIRONMENT_KEYS.map((key) => [key, process.env[key]]),
    );
    for (const key of HOME_ENVIRONMENT_KEYS) {
      process.env[key] = e2eHome;
    }

    const baseUrl = `http://127.0.0.1:${address.port}`;
    let client: PiRpcClient | undefined;
    try {
      const { createPiRpcClient } = await import(
        "@posthog/agent/pi/rpc-client"
      );
      client = createPiRpcClient({
        cliPath: rpcHostPath,
        taskContext: {
          taskId: "pi-enrichment-e2e",
          cwd: workspace,
          projectId: 1,
          apiHost: "https://us.posthog.com",
          environment: "local",
        },
        model: "claude-haiku-4-5",
        projectTrusted: false,
        providerOptions: { apiKey: "gateway-test-key", baseUrl },
        enrichment: {
          apiUrl: baseUrl,
          publicApiUrl: "https://us.posthog.com",
          projectId: 1,
          apiKey: "posthog-test-key",
        },
      });
      await client.start();
      const settled = client.waitForIdle();
      await client.prompt("Read example.ts and report what you find.");
      await settled;

      expect(eventDefinitionRequests).toBe(1);
      expect(eventStatsRequests).toBe(1);
      expect(initialModelRequest).toContain("## Rich output in replies");
      expect(initialModelRequest).toContain('<kind id=\\"...\\">');
      expect(enrichedModelRequest).toContain(
        '[PostHog] Event: \\"checkout_completed\\"',
      );
      expect(enrichedModelRequest).toContain("321 events");
      expect(enrichedModelRequest).toContain("87 users");
    } finally {
      await client?.stop();
      for (const [key, value] of previousEnvironment) {
        if (value === undefined) {
          delete process.env[key];
        } else {
          process.env[key] = value;
        }
      }
      await new Promise<void>((resolveClosed, rejectClosed) => {
        server.close((error) => {
          if (error) {
            rejectClosed(error);
          } else {
            resolveClosed();
          }
        });
      });
    }
  });
});
