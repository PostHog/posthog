import crypto from "node:crypto";
import { type ServerType, serve } from "@hono/node-server";
import { Hono } from "hono";
import type { Logger } from "../utils/logger";
import type { RemoteMcpServer } from "./schemas";

export const DEFAULT_RELAY_TIMEOUT_MS = 60_000;
/** Request payloads above this are rejected before any event is emitted. */
export const DEFAULT_MAX_REQUEST_BYTES = 64_000;

/** JSON-RPC error: the desktop app did not answer within the timeout. */
export const RELAY_TIMEOUT_CODE = -32001;
/** JSON-RPC error: the request payload exceeded the relay size cap. */
export const RELAY_PAYLOAD_TOO_LARGE_CODE = -32002;

export interface McpRelayResponse {
  requestId: string;
  server: string;
  payload?: Record<string, unknown>;
  error?: { code: number; message: string };
}

interface PendingRelayRequest {
  server: string;
  resolve: (response: McpRelayResponse) => void;
  timer: NodeJS.Timeout;
}

export interface McpRelayServerConfig {
  /** Designated relay server names; requests for other names are 404s. */
  servers: string[];
  /** Broadcast an event over the durable stream + SSE (agent-server seam). */
  emitEvent: (event: Record<string, unknown>) => void;
  /**
   * Whether any client could service a relay request. Mirrors the permission
   * relay's `hasReachableClient`: a direct SSE viewer OR an active durable
   * event stream (the desktop reads the durable stream via the agent-proxy
   * without ever connecting to the sandbox, so a stricter "saw the desktop
   * directly" signal would 503 every request in that topology). False only
   * when the run is genuinely headless — but headless runs never designate
   * relay servers, so this is defense in depth.
   */
  hasReachableClient: () => boolean;
  logger: Logger;
  requestTimeoutMs?: number;
  maxRequestBytes?: number;
  now?: () => number;
}

/**
 * Loopback HTTP MCP endpoints that relay JSON-RPC to the user's desktop app
 * over the durable event stream (docs/cloud-mcp-relay.md). Each designated
 * server gets `http://127.0.0.1:<port>/relay/<name>`, registered in the
 * session's mcpServers list as a plain streamable-HTTP server — the adapters
 * need no relay awareness. Requests correlate to `mcp_response` commands by
 * requestId, mirroring the permission-request relay.
 */
export class McpRelayServer {
  private readonly pending = new Map<string, PendingRelayRequest>();
  private readonly serverNames: Set<string>;
  /**
   * Loopback-only defense in depth: entries registered with the session carry
   * this bearer, so other sandbox processes can't use the relay as a proxy
   * into the user's network without first reading agent-server memory.
   */
  private readonly secret = crypto.randomUUID();
  private server: ServerType | null = null;
  private port: number | null = null;
  private stopped = false;
  /**
   * Whether a client has ever been reachable. Before the first client attaches
   * (a ~2s startup window while the event relay connects), we must NOT 503 —
   * an MCP client connects to each server once at session start, and a 503 in
   * that window makes it drop the server permanently. The request is buffered
   * and delivered when the client attaches, so it resolves within the timeout.
   */
  private everReachable = false;

  constructor(private readonly config: McpRelayServerConfig) {
    this.serverNames = new Set(config.servers);
  }

  async start(): Promise<void> {
    if (this.server) return;
    const app = this.createApp();
    await new Promise<void>((resolve, reject) => {
      try {
        this.server = serve(
          { fetch: app.fetch, port: 0, hostname: "127.0.0.1" },
          (info) => {
            this.port = info.port;
            resolve();
          },
        );
      } catch (error) {
        reject(error);
      }
    });
    this.config.logger.debug("MCP relay server listening", {
      port: this.port,
      servers: [...this.serverNames],
    });
  }

  /** Session mcpServers entries for the relay endpoints. Call after start(). */
  get mcpServers(): RemoteMcpServer[] {
    if (this.port === null) return [];
    return [...this.serverNames].map((name) => ({
      type: "http" as const,
      name,
      url: `http://127.0.0.1:${this.port}/relay/${encodeURIComponent(name)}`,
      headers: [{ name: "Authorization", value: `Bearer ${this.secret}` }],
    }));
  }

  /** Resolve a pending request from an `mcp_response` command. */
  resolveResponse(response: McpRelayResponse): boolean {
    const pending = this.pending.get(response.requestId);
    // Late or duplicate responses find no entry and are dropped; a response
    // naming the wrong server is treated the same (defensive correlation).
    if (!pending || pending.server !== response.server) return false;
    this.pending.delete(response.requestId);
    clearTimeout(pending.timer);
    pending.resolve(response);
    return true;
  }

  async stop(): Promise<void> {
    this.stopped = true;
    for (const [requestId, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.resolve({
        requestId,
        server: pending.server,
        error: {
          code: RELAY_TIMEOUT_CODE,
          message: "Session is shutting down",
        },
      });
    }
    this.pending.clear();
    if (this.server) {
      await new Promise<void>((resolve) => {
        this.server?.close(() => resolve());
      });
      this.server = null;
      this.port = null;
    }
  }

  private now(): number {
    return this.config.now ? this.config.now() : Date.now();
  }

  private createApp(): Hono {
    const app = new Hono();

    app.post("/relay/:server", async (c) => {
      const auth = c.req.header("Authorization");
      if (auth !== `Bearer ${this.secret}`) {
        return c.json({ error: "Unauthorized" }, 401);
      }

      const server = c.req.param("server");
      if (!this.serverNames.has(server)) {
        return c.json({ error: `Unknown relay server: ${server}` }, 404);
      }

      const reachable = this.config.hasReachableClient();
      if (reachable) this.everReachable = true;

      // Only 503 once a client has been reachable and then went away (a
      // genuine mid-run desktop disconnect). Before the first client ever
      // attaches, buffer the request instead — an MCP client connects once at
      // session start, and 503ing that startup handshake makes it drop the
      // server for the whole run. The buffered request resolves when the
      // client attaches or times out.
      if (this.stopped || (this.everReachable && !reachable)) {
        this.config.logger.debug(
          "MCP relay endpoint 503: no reachable client",
          {
            server,
          },
        );
        return c.json(
          {
            error: "MCP relay requires the desktop app, which is not connected",
          },
          503,
        );
      }

      const rawBody = await c.req.text();
      const maxBytes = this.config.maxRequestBytes ?? DEFAULT_MAX_REQUEST_BYTES;
      if (Buffer.byteLength(rawBody, "utf8") > maxBytes) {
        return c.json({
          jsonrpc: "2.0",
          id: null,
          error: {
            code: RELAY_PAYLOAD_TOO_LARGE_CODE,
            message: `MCP relay request exceeds ${maxBytes} bytes`,
          },
        });
      }

      let payload: Record<string, unknown>;
      try {
        const parsed: unknown = JSON.parse(rawBody);
        if (
          typeof parsed !== "object" ||
          parsed === null ||
          Array.isArray(parsed)
        ) {
          throw new Error("not an object");
        }
        payload = parsed as Record<string, unknown>;
      } catch {
        return c.json({
          jsonrpc: "2.0",
          id: null,
          error: { code: -32700, message: "Parse error" },
        });
      }

      const requestId = crypto.randomUUID();
      const timeoutMs =
        this.config.requestTimeoutMs ?? DEFAULT_RELAY_TIMEOUT_MS;
      const expiresAt = new Date(this.now() + timeoutMs).toISOString();
      const event = {
        type: "mcp_request",
        requestId,
        server,
        payload,
        expiresAt,
      };
      this.config.logger.debug("MCP relay request", {
        server,
        requestId,
        method: payload.method,
        isNotification: payload.id === undefined || payload.id === null,
      });

      // Notifications (no id) are fire-and-forget: emit and acknowledge.
      if (payload.id === undefined || payload.id === null) {
        this.config.emitEvent(event);
        return c.body(null, 202);
      }

      const response = await new Promise<McpRelayResponse>((resolve) => {
        const timer = setTimeout(() => {
          this.pending.delete(requestId);
          resolve({
            requestId,
            server,
            error: {
              code: RELAY_TIMEOUT_CODE,
              message: "MCP relay timed out waiting for the desktop app",
            },
          });
        }, timeoutMs);
        this.pending.set(requestId, { server, resolve, timer });
        this.config.emitEvent(event);
      });

      if (response.error) {
        return c.json({
          jsonrpc: "2.0",
          id: payload.id,
          error: response.error,
        });
      }
      // The relayed payload is the complete JSON-RPC response from the real
      // server; return it verbatim.
      return c.json(response.payload ?? null);
    });

    // Streamable HTTP allows servers to decline the optional SSE channel.
    app.get("/relay/:server", (c) =>
      c.json({ error: "Method not allowed" }, 405),
    );
    app.notFound((c) => c.json({ error: "Not found" }, 404));
    return app;
  }
}
