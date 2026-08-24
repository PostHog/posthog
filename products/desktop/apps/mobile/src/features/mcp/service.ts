import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type {
  CallToolResult,
  ReadResourceResult,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { AppState, type AppStateStatus } from "react-native";
import { useAuthStore } from "@/features/auth";
import { logger } from "@/lib/logger";

const log = logger.scope("mcp-service");

interface ServerConnection {
  installationId: string;
  serverName: string;
  proxyUrl: string;
  client: Client;
  transport: StreamableHTTPClientTransport;
}

const CLIENT_INFO = { name: "posthog-code-mobile", version: "1.0.0" };

/**
 * Mobile-side service that owns MCP `Client` connections per installation.
 *
 * Each installation gets a lazy `StreamableHTTPClientTransport` pointed at the
 * cloud-hosted proxy URL the API returned. Auth is injected per-request via
 * the user's PostHog access token in the `Authorization` header — the cloud
 * proxy strips it and forwards a fresh server-side credential to the MCP
 * server, so the mobile token never reaches the upstream.
 *
 * Connections are kept alive across screens (one per server). They're torn
 * down when the app backgrounds for more than a few seconds so we don't
 * accumulate sockets, and re-opened on demand.
 */
class McpConnectionManager {
  private connections = new Map<string, ServerConnection>();
  private pendingConnects = new Map<string, Promise<ServerConnection>>();
  private appStateSubscription: { remove(): void } | null = null;

  registerAppStateListener(): void {
    if (this.appStateSubscription) return;
    this.appStateSubscription = AppState.addEventListener(
      "change",
      (nextState) => {
        if (nextState !== "active") {
          // Background — drop all connections to avoid stale-socket churn.
          // Next request re-opens them lazily.
          void this.closeAll();
        }
      },
    );
  }

  /** Returns a connected MCP `Client` for the given installation, creating
   *  one on first use. Concurrent callers share the same pending promise. */
  async getClient(args: {
    installationId: string;
    serverName: string;
    proxyUrl: string;
  }): Promise<Client> {
    const existing = this.connections.get(args.installationId);
    if (existing) return existing.client;

    const pending = this.pendingConnects.get(args.installationId);
    if (pending) {
      const connection = await pending;
      return connection.client;
    }

    const promise = this.connect(args);
    this.pendingConnects.set(args.installationId, promise);
    try {
      const connection = await promise;
      this.connections.set(args.installationId, connection);
      return connection.client;
    } finally {
      this.pendingConnects.delete(args.installationId);
    }
  }

  private async connect(args: {
    installationId: string;
    serverName: string;
    proxyUrl: string;
  }): Promise<ServerConnection> {
    const { oauthAccessToken } = useAuthStore.getState();
    if (!oauthAccessToken) {
      throw new Error("Not authenticated");
    }

    const url = new URL(args.proxyUrl);
    const transport = new StreamableHTTPClientTransport(url, {
      requestInit: {
        headers: {
          Authorization: `Bearer ${oauthAccessToken}`,
        },
      },
    });

    const client = new Client(CLIENT_INFO, { capabilities: {} });
    await client.connect(transport);
    log.info("MCP client connected", {
      installationId: args.installationId,
      serverName: args.serverName,
    });

    return {
      installationId: args.installationId,
      serverName: args.serverName,
      proxyUrl: args.proxyUrl,
      client,
      transport,
    };
  }

  async callTool(args: {
    installationId: string;
    serverName: string;
    proxyUrl: string;
    toolName: string;
    arguments?: Record<string, unknown>;
  }): Promise<CallToolResult> {
    const client = await this.getClient(args);
    const result = await client.callTool({
      name: args.toolName,
      arguments: args.arguments ?? {},
    });
    return result as CallToolResult;
  }

  async readResource(args: {
    installationId: string;
    serverName: string;
    proxyUrl: string;
    uri: string;
  }): Promise<ReadResourceResult> {
    const client = await this.getClient(args);
    return (await client.readResource({ uri: args.uri })) as ReadResourceResult;
  }

  async getTool(args: {
    installationId: string;
    serverName: string;
    proxyUrl: string;
    toolName: string;
  }): Promise<Tool | null> {
    const client = await this.getClient(args);
    const { tools } = await client.listTools();
    return tools.find((t) => t.name === args.toolName) ?? null;
  }

  /** Close a single connection (e.g., after uninstall). */
  async close(installationId: string): Promise<void> {
    const connection = this.connections.get(installationId);
    if (!connection) return;
    this.connections.delete(installationId);
    try {
      await connection.client.close();
    } catch (err) {
      log.warn("Failed to close MCP client", { installationId, err });
    }
  }

  async closeAll(): Promise<void> {
    const ids = [...this.connections.keys()];
    await Promise.allSettled(ids.map((id) => this.close(id)));
  }
}

let manager: McpConnectionManager | null = null;

export function getMcpConnectionManager(): McpConnectionManager {
  if (!manager) {
    manager = new McpConnectionManager();
    manager.registerAppStateListener();
  }
  return manager;
}

// Exported for tests.
export { McpConnectionManager };
export type { AppStateStatus };
