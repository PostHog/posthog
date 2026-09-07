/**
 * Test-only helpers: an in-memory MCP server wired to a `TransportFactory`,
 * so ServerManager/extension tests exercise the real SDK client, handshake,
 * and JSON-RPC layer without spawning processes or opening sockets.
 */

import { createHash } from "node:crypto";
import type { Server as HttpServer } from "node:http";
import { createServer } from "node:http";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import type { TransportFactory } from "./server-manager";

export interface MockToolSpec {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
  /** Handler invoked on tools/call. */
  handler: (args: Record<string, unknown>) => {
    content: Array<Record<string, unknown>>;
    isError?: boolean;
  };
}

export interface MockMcpServer {
  transportFactory: TransportFactory;
  /** How many transports have been created (i.e. connection attempts). */
  connectionCount: () => number;
  /** The most recently connected server-side instance. */
  lastServer: () => Server | undefined;
  /** Replace the advertised tool list and notify connected clients. */
  setTools: (tools: MockToolSpec[]) => Promise<void>;
  /** Block tools/list responses until the promise resolves (race tests). */
  setListToolsGate: (gate: Promise<void> | null) => void;
  /** How many tools/list requests have been received. */
  listToolsCalls: () => number;
  /** How many tools/list responses have been sent (past any gate). */
  listToolsCompleted: () => number;
  close: () => Promise<void>;
}

export interface TokenRequest {
  grantType: string;
  code?: string;
  codeVerifier?: string;
  refreshToken?: string;
  clientId?: string;
}

export interface FakeOAuthServer {
  /** Base URL; use `<url>/mcp` as the protected server URL. */
  url: string;
  /** All token-endpoint requests received, in order. */
  tokenRequests: TokenRequest[];
  /** Dynamic registration payloads received. */
  registrations: Array<Record<string, unknown>>;
  /**
   * Arm PKCE verification: the token endpoint will reject an
   * authorization_code exchange whose `code_verifier` does not S256-hash to
   * this challenge (captured from the authorization URL by the test's
   * browser simulation).
   */
  setCodeChallenge: (challenge: string | null) => void;
  close: () => Promise<void>;
}

/** RFC 7636 S256: base64url(sha256(verifier)). */
function s256(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}

/**
 * Minimal OAuth 2.1 authorization server for exercising the SDK's real
 * discovery → dynamic registration → PKCE → token-exchange → refresh flow
 * over loopback HTTP. Accepts the fixed authorization code "test-code".
 */
export async function createFakeOAuthServer(): Promise<FakeOAuthServer> {
  const tokenRequests: TokenRequest[] = [];
  const registrations: Array<Record<string, unknown>> = [];
  let issued = 0;
  let expectedCodeChallenge: string | null = null;

  let origin = "";
  const server: HttpServer = createServer((req, res) => {
    const url = new URL(req.url ?? "/", origin || "http://127.0.0.1");
    const json = (status: number, body: unknown) => {
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body));
    };

    if (url.pathname.startsWith("/.well-known/oauth-protected-resource")) {
      json(404, { error: "not_found" });
      return;
    }
    if (
      url.pathname.startsWith("/.well-known/oauth-authorization-server") ||
      url.pathname.startsWith("/.well-known/openid-configuration")
    ) {
      json(200, {
        issuer: origin,
        authorization_endpoint: `${origin}/authorize`,
        token_endpoint: `${origin}/token`,
        registration_endpoint: `${origin}/register`,
        response_types_supported: ["code"],
        grant_types_supported: ["authorization_code", "refresh_token"],
        code_challenge_methods_supported: ["S256"],
        token_endpoint_auth_methods_supported: ["none"],
      });
      return;
    }

    let body = "";
    req.on("data", (chunk: Buffer) => {
      body += chunk.toString();
    });
    req.on("end", () => {
      if (req.method === "POST" && url.pathname === "/register") {
        const payload = JSON.parse(body) as Record<string, unknown>;
        registrations.push(payload);
        json(201, {
          client_id: "client-123",
          client_id_issued_at: Math.floor(Date.now() / 1000),
          redirect_uris: payload.redirect_uris,
          token_endpoint_auth_method: "none",
          grant_types: ["authorization_code", "refresh_token"],
          response_types: ["code"],
        });
        return;
      }
      if (req.method === "POST" && url.pathname === "/token") {
        const params = new URLSearchParams(body);
        const grantType = params.get("grant_type") ?? "";
        tokenRequests.push({
          grantType,
          ...(params.get("code") !== null
            ? { code: params.get("code") as string }
            : {}),
          ...(params.get("code_verifier") !== null
            ? { codeVerifier: params.get("code_verifier") as string }
            : {}),
          ...(params.get("refresh_token") !== null
            ? { refreshToken: params.get("refresh_token") as string }
            : {}),
          ...(params.get("client_id") !== null
            ? { clientId: params.get("client_id") as string }
            : {}),
        });
        if (grantType === "authorization_code") {
          const verifier = params.get("code_verifier");
          if (params.get("code") !== "test-code" || !verifier) {
            json(400, { error: "invalid_grant" });
            return;
          }
          // Real PKCE check when the test armed a challenge — a wrong or
          // stale verifier must fail the exchange like a real server.
          if (
            expectedCodeChallenge !== null &&
            s256(verifier) !== expectedCodeChallenge
          ) {
            json(400, {
              error: "invalid_grant",
              error_description: "PKCE verification failed",
            });
            return;
          }
        } else if (grantType === "refresh_token") {
          if (!params.get("refresh_token")) {
            json(400, { error: "invalid_grant" });
            return;
          }
        } else {
          json(400, { error: "unsupported_grant_type" });
          return;
        }
        issued++;
        json(200, {
          access_token: `access-${issued}`,
          token_type: "bearer",
          expires_in: 3600,
          refresh_token: `refresh-${issued}`,
        });
        return;
      }
      json(404, { error: "not_found" });
    });
  });

  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address();
  const port =
    typeof address === "object" && address !== null ? address.port : 0;
  origin = `http://127.0.0.1:${port}`;

  return {
    url: origin,
    tokenRequests,
    registrations,
    setCodeChallenge: (challenge) => {
      expectedCodeChallenge = challenge;
    },
    close: () =>
      new Promise<void>((resolve) => {
        server.close(() => resolve());
      }),
  };
}

export function createMockMcpServer(
  initialTools: MockToolSpec[],
): MockMcpServer {
  let tools = initialTools;
  const servers: Server[] = [];
  let connections = 0;
  let listGate: Promise<void> | null = null;
  let listCalls = 0;
  let listCompleted = 0;

  const listResult = () => ({
    tools: tools.map((tool) => ({
      name: tool.name,
      description: tool.description ?? `mock tool ${tool.name}`,
      inputSchema: tool.inputSchema ?? { type: "object", properties: {} },
    })),
  });

  const buildServer = (): Server => {
    const server = new Server(
      { name: "mock-mcp", version: "1.0.0" },
      { capabilities: { tools: { listChanged: true } } },
    );
    server.setRequestHandler(ListToolsRequestSchema, async () => {
      listCalls++;
      if (listGate) await listGate;
      listCompleted++;
      return listResult();
    });
    server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const tool = tools.find((t) => t.name === request.params.name);
      if (!tool) {
        return {
          content: [
            { type: "text", text: `unknown tool ${request.params.name}` },
          ],
          isError: true,
        };
      }
      return tool.handler(
        (request.params.arguments ?? {}) as Record<string, unknown>,
      );
    });
    return server;
  };

  return {
    transportFactory: async () => {
      connections++;
      const [clientTransport, serverTransport] =
        InMemoryTransport.createLinkedPair();
      const server = buildServer();
      servers.push(server);
      await server.connect(serverTransport);
      return clientTransport;
    },
    connectionCount: () => connections,
    lastServer: () => servers[servers.length - 1],
    setListToolsGate: (gate) => {
      listGate = gate;
    },
    listToolsCalls: () => listCalls,
    listToolsCompleted: () => listCompleted,
    setTools: async (next) => {
      tools = next;
      await Promise.allSettled(
        servers.map((server) =>
          server.notification({ method: "notifications/tools/list_changed" }),
        ),
      );
    },
    close: async () => {
      await Promise.allSettled(servers.map((server) => server.close()));
    },
  };
}
