/**
 * MCP server lifecycle manager.
 *
 * Deliberately thin: the official SDK handles protocol state, transports,
 * and stdio process lifecycle. This module handles:
 *   - 3-state lifecycle per server (stopped / starting / ready)
 *   - Retry with a fixed delay schedule (injectable for tests)
 *   - roots/list capability for the MCP handshake
 *   - notifications/tools/list_changed → tool refresh callback
 *   - Log capture (stderr + server log notifications, circular buffer)
 *   - PID tracking for a safety-net SIGKILL if SDK cleanup fails
 */

import type { OAuthClientProvider } from "@modelcontextprotocol/sdk/client/auth.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import {
  ListRootsRequestSchema,
  LoggingMessageNotificationSchema,
  ToolListChangedNotificationSchema,
} from "@modelcontextprotocol/sdk/types.js";
import type { McpAuthStorage } from "./auth-storage";
import type { McpConfig, McpServerConfig, McpSettings } from "./config";
import { McpError } from "./errors";
import { McpOAuthProvider } from "./oauth-provider";

export type ServerState = "stopped" | "starting" | "ready";

/** Fixed retry delay schedule — predictable, no jitter math needed. */
const DEFAULT_RETRY_DELAYS_MS: readonly number[] = [
  1_000, 3_000, 5_000, 10_000, 30_000,
];

/** Maximum log lines stored per server (circular buffer). */
const LOG_BUFFER_SIZE = 100;

export interface ManagedServer {
  name: string;
  config: McpServerConfig;
  state: ServerState;
  client: Client | null;
  /** PID of the child process (stdio transport only), for safety-net cleanup. */
  childPid: number | null;
  retryCount: number;
  lastError: Error | null;
  /** Recent stderr / log-notification lines from the server. */
  log: string[];
  healthCheckTimer: ReturnType<typeof setInterval> | null;
  /** Pending retry timeout — cleared on shutdown to prevent ghost reconnects. */
  retryTimer: ReturnType<typeof setTimeout> | null;
  /** Idle-disconnect ticker for `lifecycle: "lazy"` servers with `idleTimeoutMs`. */
  idleTimer: ReturnType<typeof setInterval> | null;
  /** Updated by `touch()` on every tool call; drives the idle-disconnect ticker. */
  lastUsedAt: number;
}

/** Called after a server connects and whenever its tool list changes. */
export type ToolRefreshCallback = (
  serverName: string,
  client: Client,
) => Promise<void>;

/** Called when a ready server's connection is lost (crash, dropped link). */
export type DisconnectCallback = (serverName: string) => void;

/**
 * Creates a transport for a server. Injectable for tests. `authProvider`
 * is supplied for http/sse servers with OAuth configured; it attaches and
 * silently refreshes stored tokens (background mode — it never opens a
 * browser; interactive authorization happens through `/mcp:auth`).
 */
export type TransportFactory = (
  serverName: string,
  config: McpServerConfig,
  appendLog: (line: string) => void,
  authProvider?: OAuthClientProvider,
) => Transport | Promise<Transport>;

export const defaultTransportFactory: TransportFactory = (
  _serverName,
  config,
  appendLog,
  authProvider,
) => {
  switch (config.transport) {
    case "stdio": {
      // process.env may contain undefined values; spawn drops them silently,
      // but the SDK's env type wants Record<string, string>.
      const env: Record<string, string> = {};
      for (const [key, value] of Object.entries(process.env)) {
        if (value !== undefined) env[key] = value;
      }
      Object.assign(env, config.env ?? {});
      const transport = new StdioClientTransport({
        command: config.command as string,
        args: config.args,
        env,
        stderr: "pipe",
      });
      transport.stderr?.on("data", (chunk: Buffer) => {
        for (const line of chunk.toString().split("\n")) {
          if (line.trim().length > 0) appendLog(line);
        }
      });
      return transport;
    }
    case "streamable-http":
      return new StreamableHTTPClientTransport(new URL(config.url as string), {
        ...(config.headers ? { requestInit: { headers: config.headers } } : {}),
        ...(authProvider ? { authProvider } : {}),
      });
    case "sse":
      return new SSEClientTransport(new URL(config.url as string), {
        ...(config.headers ? { requestInit: { headers: config.headers } } : {}),
        ...(authProvider ? { authProvider } : {}),
      });
  }
};

export interface ServerManagerOptions {
  transportFactory?: TransportFactory;
  /** Override the retry schedule (tests). */
  retryDelaysMs?: readonly number[];
  /** OAuth credential storage; required for servers with `auth` config. */
  authStorage?: McpAuthStorage;
}

export class ServerManager {
  private readonly servers = new Map<string, ManagedServer>();
  private readonly transportFactory: TransportFactory;
  private readonly retryDelaysMs: readonly number[];
  private readonly authStorage: McpAuthStorage | undefined;
  private settings: McpSettings;
  private onToolRefresh: ToolRefreshCallback | null = null;
  private onDisconnect: DisconnectCallback | null = null;

  constructor(config: McpConfig, options: ServerManagerOptions = {}) {
    this.settings = config.settings;
    this.transportFactory = options.transportFactory ?? defaultTransportFactory;
    this.retryDelaysMs = options.retryDelaysMs ?? DEFAULT_RETRY_DELAYS_MS;
    this.authStorage = options.authStorage;
    this.populate(config);
  }

  /**
   * Register the callback invoked on initial connect and whenever a
   * server's tool list changes (this is where tools get (re)registered).
   */
  setToolRefreshCallback(cb: ToolRefreshCallback): void {
    this.onToolRefresh = cb;
  }

  /**
   * Register the callback invoked when a ready server's connection drops
   * unexpectedly (use it to deactivate the server's tools while the
   * background reconnect runs).
   */
  setDisconnectCallback(cb: DisconnectCallback): void {
    this.onDisconnect = cb;
  }

  getServer(name: string): ManagedServer | undefined {
    return this.servers.get(name);
  }

  getAllServers(): ManagedServer[] {
    return [...this.servers.values()];
  }

  /**
   * Record tool-call activity for a server, resetting its idle-disconnect
   * countdown (`lifecycle: "lazy"` + `idleTimeoutMs`). Called by the tool
   * bridge and the `mcp` proxy tool on every dispatch.
   */
  touch(name: string): void {
    const server = this.servers.get(name);
    if (server) server.lastUsedAt = Date.now();
  }

  /** Effective per-request timeout for a server. */
  getRequestTimeoutMs(name: string): number {
    return (
      this.servers.get(name)?.config.requestTimeoutMs ??
      this.settings.requestTimeoutMs
    );
  }

  /** Human-readable status summary for the /mcp command. */
  getStatusSummary(): string {
    const all = this.getAllServers();
    if (all.length === 0) {
      return "mcp: no servers configured (create mcp.json in your agent dir or project .pi/)";
    }
    const lines = all.map((server) => {
      const icon =
        server.state === "ready"
          ? "✓"
          : server.state === "starting"
            ? "⟳"
            : "✗";
      const err = server.lastError ? ` — ${server.lastError.message}` : "";
      return `  ${icon} ${server.name} (${server.state})${err}`;
    });
    const ready = all.filter((server) => server.state === "ready").length;
    return [`MCP: ${ready}/${all.length} servers ready`, ...lines].join("\n");
  }

  /** Recent log output for a server. */
  getServerLogs(name: string): string {
    const server = this.servers.get(name);
    if (!server) return `No server named "${name}"`;
    if (server.log.length === 0) return `(no output from ${name})`;
    return server.log.join("\n");
  }

  /**
   * Start a server and connect to it. `cwd` is exposed to the server through
   * roots/list as the workspace root. No-op if already starting or ready.
   */
  async startServer(name: string, cwd: string): Promise<void> {
    const server = this.servers.get(name);
    if (!server) {
      throw new McpError(`Unknown server "${name}"`, name, "config");
    }
    if (server.state !== "stopped") return;
    // Cancel any pending background retry — connect() below supersedes it.
    if (server.retryTimer) {
      clearTimeout(server.retryTimer);
      server.retryTimer = null;
    }
    // Reset retries on explicit start — allows /mcp:start after exhaustion.
    server.retryCount = 0;
    await this.connect(server, cwd);
  }

  async stopServer(name: string): Promise<void> {
    const server = this.servers.get(name);
    if (!server) return;
    // Always run shutdown — even for a "stopped" server it cancels any
    // pending background retry timer.
    await this.shutdown(server);
  }

  async shutdownAll(): Promise<void> {
    await Promise.allSettled(
      [...this.servers.values()].map((server) => this.shutdown(server)),
    );
  }

  private populate(config: McpConfig): void {
    for (const [name, serverConfig] of Object.entries(config.mcpServers)) {
      this.servers.set(name, {
        name,
        config: serverConfig,
        state: "stopped",
        client: null,
        childPid: null,
        retryCount: 0,
        lastError: null,
        log: [],
        healthCheckTimer: null,
        retryTimer: null,
        idleTimer: null,
        lastUsedAt: Date.now(),
      });
    }
  }

  /**
   * Background OAuth provider for servers with `auth` configured: attaches
   * stored tokens and refreshes them silently, but never opens a browser
   * (no redirect callback — a required fresh authorization surfaces as an
   * UnauthorizedError pointing the user at /mcp:auth).
   */
  private createAuthProvider(
    server: ManagedServer,
  ): OAuthClientProvider | undefined {
    if (
      !server.config.auth ||
      server.config.transport === "stdio" ||
      !server.config.url ||
      !this.authStorage
    ) {
      return undefined;
    }
    return new McpOAuthProvider(
      server.name,
      server.config.url,
      server.config.auth,
      this.authStorage,
    );
  }

  private appendLog(server: ManagedServer, line: string): void {
    server.log.push(line);
    if (server.log.length > LOG_BUFFER_SIZE) server.log.shift();
  }

  private async connect(server: ManagedServer, cwd: string): Promise<void> {
    server.state = "starting";
    server.lastError = null;

    let transport: Transport;
    try {
      transport = await this.transportFactory(
        server.name,
        server.config,
        (line) => this.appendLog(server, line),
        this.createAuthProvider(server),
      );
    } catch (err) {
      // Guard: shutdown() may have flipped state to "stopped" while the
      // factory ran — don't schedule a ghost retry after an explicit stop.
      if (server.state !== "starting") return;
      server.state = "stopped";
      server.lastError = err instanceof Error ? err : new Error(String(err));
      this.scheduleRetry(server, cwd);
      return;
    }

    const client = new Client(
      { name: "posthog-harness-mcp", version: "1.0.0" },
      { capabilities: { roots: { listChanged: true } } },
    );

    // Expose the workspace root to the MCP server.
    client.setRequestHandler(ListRootsRequestSchema, async () => ({
      roots: [{ uri: `file://${cwd}`, name: "workspace" }],
    }));

    // tools/list_changed → re-discover tools and update pi registrations.
    client.setNotificationHandler(
      ToolListChangedNotificationSchema,
      async () => {
        if (this.onToolRefresh && server.client) {
          try {
            await this.onToolRefresh(server.name, server.client);
          } catch (err) {
            this.appendLog(
              server,
              `[mcp] tool refresh failed: ${err instanceof Error ? err.message : String(err)}`,
            );
          }
        }
      },
    );

    // notifications/message → structured server logging into the buffer.
    client.setNotificationHandler(
      LoggingMessageNotificationSchema,
      async (notification) => {
        const {
          level = "info",
          logger = server.name,
          data,
        } = notification.params ?? {};
        const msg = typeof data === "string" ? data : JSON.stringify(data);
        this.appendLog(server, `[${level}] ${logger}: ${msg}`);
      },
    );

    try {
      await client.connect(transport);
    } catch (err) {
      try {
        await client.close();
      } catch {
        // best effort
      }
      // Guard: shutdown() may have flipped state to "stopped" while
      // connecting — don't schedule a ghost retry after an explicit stop.
      if (server.state !== "starting") return;
      server.state = "stopped";
      server.lastError = err instanceof Error ? err : new Error(String(err));
      this.scheduleRetry(server, cwd);
      return;
    }

    // Guard: shutdown() may have flipped state to "stopped" while connecting;
    // it cannot close this local client, so close it here.
    if (server.state !== "starting") {
      try {
        await client.close();
      } catch {
        // best effort
      }
      return;
    }

    if (server.config.transport === "stdio") {
      server.childPid = (transport as StdioClientTransport).pid ?? null;
    }

    server.client = client;
    server.state = "ready";
    server.retryCount = 0;
    server.lastError = null;
    server.lastUsedAt = Date.now();

    // Detect crashes and dropped connections: without this, a dead server
    // would stay "ready" with active tools bound to a closed client forever.
    // shutdown()/handleConnectionLoss() null out server.client before
    // closing, so our own intentional closes are filtered by the guard in
    // handleConnectionLoss.
    client.onclose = () => {
      this.handleConnectionLoss(
        server,
        client,
        cwd,
        "connection closed unexpectedly",
      );
    };

    if (server.config.healthCheckIntervalMs) {
      server.healthCheckTimer = setInterval(async () => {
        try {
          await client.ping();
        } catch {
          this.handleConnectionLoss(server, client, cwd, "health check failed");
        }
      }, server.config.healthCheckIntervalMs);
      server.healthCheckTimer.unref?.();
    }

    // Idle-disconnect: only for lazy servers that opt in. Metadata stays
    // cached (tool-cache.ts) so search keeps working; the next call to one
    // of its tools reconnects transparently.
    if (server.config.lifecycle === "lazy" && server.config.idleTimeoutMs) {
      const idleTimeoutMs = server.config.idleTimeoutMs;
      const checkIntervalMs = Math.min(idleTimeoutMs, 60_000);
      server.idleTimer = setInterval(() => {
        if (Date.now() - server.lastUsedAt >= idleTimeoutMs) {
          void this.stopServer(server.name);
        }
      }, checkIntervalMs);
      server.idleTimer.unref?.();
    }

    if (this.onToolRefresh) {
      try {
        await this.onToolRefresh(server.name, client);
      } catch (err) {
        this.appendLog(
          server,
          `[mcp] initial tool registration failed: ${err instanceof Error ? err.message : String(err)}`,
        );
        server.lastError = err instanceof Error ? err : new Error(String(err));
      }
    }
  }

  /**
   * Handle an unexpected connection loss for a ready server: flip state,
   * notify the disconnect callback (deactivates tools), and schedule a
   * background reconnect. No-op when `client` is not the server's current
   * client — that means the close was our own shutdown/stop, or a stale
   * health-check ping racing a newer connection.
   */
  private handleConnectionLoss(
    server: ManagedServer,
    client: Client,
    cwd: string,
    reason: string,
  ): void {
    if (server.client !== client) return;
    if (server.healthCheckTimer) {
      clearInterval(server.healthCheckTimer);
      server.healthCheckTimer = null;
    }
    if (server.idleTimer) {
      clearInterval(server.idleTimer);
      server.idleTimer = null;
    }
    server.client = null;
    server.state = "stopped";
    server.lastError = new Error(reason);
    this.appendLog(server, `[mcp] ${reason}, reconnecting`);
    this.onDisconnect?.(server.name);
    void client.close().catch(() => {
      // best effort — the connection is already gone
    });
    this.scheduleRetry(server, cwd);
  }

  /**
   * Schedule a background reconnect attempt. Fire-and-forget so a failing
   * eager server never blocks session start; `shutdown()` clears the pending
   * timer to prevent ghost reconnects.
   */
  private scheduleRetry(server: ManagedServer, cwd: string): void {
    const maxRetries = this.settings.maxRetries;
    if (server.retryCount >= maxRetries) {
      this.appendLog(
        server,
        `[mcp] giving up after ${maxRetries} retries: ${server.lastError?.message ?? "unknown error"}`,
      );
      return;
    }

    const delayMs =
      this.retryDelaysMs[
        Math.min(server.retryCount, this.retryDelaysMs.length - 1)
      ] ?? 30_000;
    server.retryCount++;
    this.appendLog(
      server,
      `[mcp] retrying in ${delayMs}ms (attempt ${server.retryCount}/${maxRetries})`,
    );

    server.retryTimer = setTimeout(() => {
      server.retryTimer = null;
      // May have been stopped or restarted externally while waiting.
      if (server.state !== "stopped") return;
      void this.connect(server, cwd);
    }, delayMs);
    server.retryTimer.unref?.();
  }

  private async shutdown(server: ManagedServer): Promise<void> {
    if (server.retryTimer) {
      clearTimeout(server.retryTimer);
      server.retryTimer = null;
    }
    if (server.healthCheckTimer) {
      clearInterval(server.healthCheckTimer);
      server.healthCheckTimer = null;
    }
    if (server.idleTimer) {
      clearInterval(server.idleTimer);
      server.idleTimer = null;
    }
    if (server.state === "stopped" && !server.client) return;

    server.state = "stopped";
    server.lastError = null;
    const client = server.client;
    const pid = server.childPid;
    server.client = null;
    server.childPid = null;

    try {
      // The SDK handles transport-specific cleanup (stdio: close stdin, wait
      // for exit, SIGTERM/SIGKILL; http/sse: close connections).
      await client?.close();
    } catch {
      // Safety net: force-kill the subprocess if SDK cleanup failed.
      if (pid !== null) {
        try {
          process.kill(pid, "SIGKILL");
        } catch {
          // Process may already be dead.
        }
      }
    }
  }
}
