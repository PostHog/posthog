import { Client } from "@modelcontextprotocol/sdk/client";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { Tool } from "@modelcontextprotocol/sdk/types.js";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import {
  type IUrlLauncher,
  URL_LAUNCHER_SERVICE,
} from "@posthog/platform/url-launcher";
import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  BUILTIN_POSTHOG_SERVER_NAME,
  EXEC_TOOL_NAME,
  LEGACY_RESOURCE_URI_META_KEY,
  type McpAppsDiscoveryCompleteEvent,
  McpAppsServiceEvent,
  type McpAppsServiceEvents,
  type McpAppsToolCancelledEvent,
  type McpAppsToolInputEvent,
  type McpAppsToolResultEvent,
  type McpResourceUiMeta,
  type McpServerConnectionConfig,
  type McpToolUiAssociation,
  type McpToolUiMeta,
  type McpUiResource,
  POSTHOG_EXEC_TOOL_KEY,
  resolveResultResourceUri,
} from "./schemas";

function summarizeResult(result: unknown): Record<string, unknown> {
  if (result == null || typeof result !== "object") {
    return { resultType: typeof result };
  }
  const obj = result as Record<string, unknown>;
  const meta = obj._meta;
  const hasMeta = meta != null && typeof meta === "object";
  const metaObj = hasMeta ? (meta as Record<string, unknown>) : undefined;
  return {
    resultType: "object",
    resultKeys: Object.keys(obj),
    hasMeta,
    metaKeys: metaObj ? Object.keys(metaObj) : undefined,
    metaUi: metaObj?.ui,
    legacyResourceUri: metaObj?.[LEGACY_RESOURCE_URI_META_KEY],
    resolvedResourceUri: resolveResultResourceUri(result),
  };
}

const UI_MIME_TYPE = "text/html;profile=mcp-app";
const MAX_HTML_SIZE = 5 * 1024 * 1024; // 5MB

interface ServerConnection {
  name: string;
  client: Client;
  transport: StreamableHTTPClientTransport;
}

@injectable()
export class McpAppsService extends TypedEventEmitter<McpAppsServiceEvents> {
  private connections = new Map<string, ServerConnection>();
  private resourceCache = new Map<string, McpUiResource>();
  private toolAssociations = new Map<string, McpToolUiAssociation>();
  private toolDefinitions = new Map<string, Tool>();
  private serverConfigs = new Map<string, McpServerConnectionConfig>();
  private configResolver?: (serverName: string) => Promise<void>;
  private pendingConnections = new Map<string, Promise<ServerConnection>>();
  private pendingFetches = new Map<string, Promise<McpUiResource | null>>();
  private resourceMetaCache = new Map<string, McpResourceUiMeta>();
  private readonly log: ScopedLogger;

  constructor(
    @inject(URL_LAUNCHER_SERVICE)
    private readonly urlLauncher: IUrlLauncher,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    super();

    this.log = rootLogger.scope("mcp-apps-service");
  }

  /**
   * Store server configs for lazy connections later.
   * No connections are created at this point.
   */
  setServerConfigs(configs: McpServerConnectionConfig[]): void {
    this.serverConfigs.clear();
    for (const config of configs) {
      this.serverConfigs.set(config.name, config);
    }
  }

  /**
   * Merge server configs without clearing existing ones. Cloud runs never run a
   * local agent session (the agent lives in the sandbox), so setServerConfigs is
   * never called for them and a cloud run's UI-app resource fetch has no config
   * to connect through ("No server config for: posthog"). This registers the
   * config on demand so the card can load.
   */
  addServerConfigs(configs: McpServerConnectionConfig[]): void {
    for (const config of configs) {
      this.serverConfigs.set(config.name, config);
    }
  }

  /**
   * Register a fallback that lazily supplies a missing server config (expected to
   * call addServerConfigs). getOrCreateConnection invokes it when a config is
   * absent — the path cloud runs hit, since no local session ever registered
   * their servers — so a UI-app resource fetch self-heals instead of throwing.
   */
  setConfigResolver(resolver: (serverName: string) => Promise<void>): void {
    this.configResolver = resolver;
  }

  /**
   * Called when the agent confirms MCP servers are connected.
   * Connects to each server, calls listTools() to discover _meta.ui fields
   * (which the agent SDK strips), then populates tool associations and
   * emits DiscoveryComplete.
   */
  async handleDiscovery(serverNames: string[]): Promise<void> {
    await Promise.allSettled(
      serverNames
        .filter((name) => this.serverConfigs.has(name))
        .map((name) => this.discoverServerUiTools(name)),
    );

    const toolKeys = [...this.toolAssociations.keys()];
    this.log.info("Discovery complete", {
      serverNames,
      toolKeys,
      associationCount: this.toolAssociations.size,
    });

    this.emit(McpAppsServiceEvent.DiscoveryComplete, {
      toolKeys,
    } satisfies McpAppsDiscoveryCompleteEvent);
  }

  /**
   * Connect to a single server and call listTools() to discover which
   * tools have _meta.ui fields. The connection is kept for later reuse
   * (proxy calls, resource reads, lazy HTML fetches).
   */
  private async discoverServerUiTools(serverName: string): Promise<void> {
    try {
      const conn = await this.getOrCreateConnection(serverName);

      const [toolsList, resourcesList] = await Promise.all([
        conn.client.listTools(),
        conn.client.listResources().catch((err) => {
          this.log.warn("listResources failed during discovery", {
            serverName,
            error: err instanceof Error ? err.message : String(err),
          });
          return null;
        }),
      ]);

      this.log.info("discoverServerUiTools: listed tools", {
        serverName,
        toolNames: toolsList.tools.map((t) => t.name),
        hasExecTool:
          serverName === BUILTIN_POSTHOG_SERVER_NAME &&
          toolsList.tools.some((t) => t.name === EXEC_TOOL_NAME),
        resourceUris: resourcesList?.resources.map((r) => r.uri),
      });

      for (const tool of toolsList.tools) {
        if (
          serverName === BUILTIN_POSTHOG_SERVER_NAME &&
          tool.name === EXEC_TOOL_NAME
        ) {
          this.toolDefinitions.set(POSTHOG_EXEC_TOOL_KEY, tool);
        }

        const uiMeta = (tool as McpToolUiMeta)._meta?.ui;
        if (!uiMeta?.resourceUri) continue;

        const toolKey = `mcp__${serverName}__${tool.name}`;
        this.toolAssociations.set(toolKey, {
          toolKey,
          serverName,
          toolName: tool.name,
          resourceUri: uiMeta.resourceUri,
          visibility: uiMeta.visibility,
        });
        this.toolDefinitions.set(toolKey, tool);
      }

      // Cache resource metadata (CSP, permissions) for use in fetchUiResource
      if (resourcesList) {
        for (const resource of resourcesList.resources) {
          const meta = resource as McpResourceUiMeta;
          if (meta._meta?.ui) {
            this.resourceMetaCache.set(resource.uri, meta);
          }
        }
      }
    } catch (err) {
      this.log.warn("Failed to discover UI tools for server", {
        serverName,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  /**
   * Get or create a lazy MCP connection for a server.
   * Deduplicates concurrent connection attempts for the same server.
   */
  private async getOrCreateConnection(
    serverName: string,
  ): Promise<ServerConnection> {
    const existing = this.connections.get(serverName);
    if (existing) {
      this.log.debug("Reusing existing MCP connection", { serverName });
      return existing;
    }

    // Deduplicate concurrent connection attempts. The pending entry must cover
    // the config-resolver await too, or two concurrent first fetches for the
    // same server would both resolve and connect, leaking a connection.
    const pending = this.pendingConnections.get(serverName);
    if (pending) {
      this.log.info("Joining pending MCP connection attempt", { serverName });
      return pending;
    }

    const connectionPromise = this.resolveConfigAndConnect(serverName);
    this.pendingConnections.set(serverName, connectionPromise);

    try {
      const conn = await connectionPromise;
      this.connections.set(serverName, conn);
      return conn;
    } finally {
      this.pendingConnections.delete(serverName);
    }
  }

  private async resolveConfigAndConnect(
    serverName: string,
  ): Promise<ServerConnection> {
    let config = this.serverConfigs.get(serverName);
    if (!config && this.configResolver) {
      await this.configResolver(serverName);
      config = this.serverConfigs.get(serverName);
    }
    if (!config) {
      throw new Error(`No server config for: ${serverName}`);
    }
    return this.createConnection(config);
  }

  private async createConnection(
    config: McpServerConnectionConfig,
  ): Promise<ServerConnection> {
    const transport = new StreamableHTTPClientTransport(new URL(config.url), {
      requestInit: {
        headers: config.headers,
      },
    });

    const client = new Client(
      { name: "posthog-code", version: "1.0.0" },
      {
        capabilities: {
          extensions: {
            "io.modelcontextprotocol/ui": {
              mimeTypes: [UI_MIME_TYPE],
            },
          },
        } as Record<string, unknown>,
      },
    );

    await client.connect(transport);

    this.log.info("Lazy MCP connection established", {
      serverName: config.name,
      serverVersion: client.getServerVersion(),
    });

    return { name: config.name, client, transport };
  }

  /**
   * Fetch the UI resource for a registration-discovered tool, by its tool key.
   */
  async getUiResourceForTool(toolKey: string): Promise<McpUiResource | null> {
    const association = this.toolAssociations.get(toolKey);
    if (!association) {
      this.log.debug("getUiResourceForTool: no association found", { toolKey });
      return null;
    }
    return this.fetchUiResourceByUri(
      association.serverName,
      association.resourceUri,
    );
  }

  /**
   * Fetch a UI resource directly by its `ui://` URI. Used by the built-in
   * PostHog `exec` path, where the resource URI is resolved per call from the
   * tool result's `_meta` (in the renderer) rather than from a registered
   * tool->UI association. Because the renderer derives it from the persisted
   * conversation, exec UI apps survive app restarts — unlike the old in-memory
   * per-call association map.
   */
  async getUiResourceByUri(
    serverName: string,
    resourceUri: string,
  ): Promise<McpUiResource | null> {
    if (!resourceUri.startsWith("ui://")) {
      this.log.warn("getUiResourceByUri: rejecting non-ui:// URI", {
        serverName,
        resourceUri,
      });
      return null;
    }
    return this.fetchUiResourceByUri(serverName, resourceUri);
  }

  /**
   * Lazily fetch + cache a UI resource's HTML, deduplicating concurrent fetches
   * for the same URI. Shared by the registration and per-call exec paths.
   */
  private async fetchUiResourceByUri(
    serverName: string,
    resourceUri: string,
  ): Promise<McpUiResource | null> {
    const cached = this.resourceCache.get(resourceUri);
    if (cached) {
      this.log.debug("fetchUiResourceByUri: cache hit", {
        serverName,
        resourceUri,
      });
      return cached;
    }

    const pendingFetch = this.pendingFetches.get(resourceUri);
    if (pendingFetch) {
      this.log.debug("fetchUiResourceByUri: joining pending fetch", {
        serverName,
        resourceUri,
      });
      return pendingFetch;
    }

    this.log.debug("fetchUiResourceByUri: starting lazy fetch", {
      serverName,
      resourceUri,
    });
    const fetchPromise = this.doFetchUiResource(serverName, resourceUri);
    this.pendingFetches.set(resourceUri, fetchPromise);
    try {
      return await fetchPromise;
    } finally {
      this.pendingFetches.delete(resourceUri);
    }
  }

  private async doFetchUiResource(
    serverName: string,
    resourceUri: string,
  ): Promise<McpUiResource | null> {
    let resourceResult: Awaited<ReturnType<Client["readResource"]>>;
    try {
      const conn = await this.getOrCreateConnection(serverName);
      resourceResult = await conn.client.readResource({ uri: resourceUri });
    } catch (err) {
      // Connection/read failures are transient — most notably "No server config
      // for: posthog" during the boot race, before a session populates configs.
      // Rethrow so the caller's query surfaces an error and retries, instead of
      // caching a permanent `null` for this (shared) resource URI and poisoning
      // every later call that reuses it.
      this.log.warn("Failed to fetch UI resource (transient — will retry)", {
        serverName,
        uri: resourceUri,
        error: err instanceof Error ? err.message : String(err),
      });
      throw err;
    }

    const textContent = resourceResult.contents.find(
      (c) => "text" in c && c.mimeType === UI_MIME_TYPE,
    );
    if (!textContent || !("text" in textContent)) {
      this.log.warn("UI resource had no matching text content", {
        serverName,
        uri: resourceUri,
        contentsCount: resourceResult.contents.length,
      });
      return null;
    }

    if (textContent.text.length > MAX_HTML_SIZE) {
      this.log.warn("UI resource HTML exceeds size limit", {
        uri: resourceUri,
        size: textContent.text.length,
        limit: MAX_HTML_SIZE,
      });
      return null;
    }

    const resourceMeta = this.resourceMetaCache.get(resourceUri);

    const resource: McpUiResource = {
      uri: resourceUri,
      name: resourceMeta?.name,
      mimeType: UI_MIME_TYPE,
      csp: resourceMeta?._meta?.ui?.csp,
      permissions: resourceMeta?._meta?.ui?.permissions,
      html: textContent.text,
      serverName,
    };

    this.resourceCache.set(resourceUri, resource);
    this.log.info("Lazily fetched and cached UI resource", {
      serverName,
      uri: resourceUri,
      htmlLength: textContent.text.length,
      hasCsp: !!resource.csp,
    });

    return resource;
  }

  hasUiForTool(toolKey: string): boolean {
    const has = this.toolAssociations.has(toolKey);
    this.log.debug("hasUiForTool", { toolKey, result: has });
    return has;
  }

  getToolDefinition(toolKey: string): Tool | null {
    return this.toolDefinitions.get(toolKey) ?? null;
  }

  async proxyToolCall(
    serverName: string,
    toolName: string,
    args?: Record<string, unknown>,
  ): Promise<unknown> {
    // Validate visibility: reject if tool is model-only
    const toolKey = `mcp__${serverName}__${toolName}`;
    const association = this.toolAssociations.get(toolKey);
    if (association?.visibility && !association.visibility.includes("app")) {
      throw new Error(
        `Tool "${toolName}" is not accessible to apps (visibility: ${association.visibility.join(", ")})`,
      );
    }

    const conn = await this.getOrCreateConnection(serverName);
    const result = await conn.client.callTool({
      name: toolName,
      arguments: args,
    });

    return result;
  }

  async proxyResourceRead(serverName: string, uri: string): Promise<unknown> {
    // Only allow ui:// scheme reads
    if (!uri.startsWith("ui://")) {
      throw new Error(`Only ui:// URIs are allowed, got: ${uri}`);
    }

    const conn = await this.getOrCreateConnection(serverName);
    const result = await conn.client.readResource({ uri });
    return result;
  }

  async openLink(url: string): Promise<void> {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      throw new Error(
        `Only http/https URLs are allowed, got: ${parsed.protocol}`,
      );
    }
    await this.urlLauncher.launch(url);
  }

  notifyToolInput(toolKey: string, toolCallId: string, args: unknown): void {
    this.log.info("notifyToolInput", { toolKey, toolCallId });
    this.emit(McpAppsServiceEvent.ToolInput, {
      toolKey,
      toolCallId,
      args,
    } satisfies McpAppsToolInputEvent);
  }

  notifyToolResult(
    toolKey: string,
    toolCallId: string,
    result: unknown,
    isError?: boolean,
  ): void {
    this.log.info("notifyToolResult", {
      toolKey,
      toolCallId,
      isError,
      ...summarizeResult(result),
    });

    this.emit(McpAppsServiceEvent.ToolResult, {
      toolKey,
      toolCallId,
      result,
      isError,
    } satisfies McpAppsToolResultEvent);
  }

  notifyToolCancelled(toolKey: string, toolCallId: string): void {
    this.log.info("notifyToolCancelled", { toolKey, toolCallId });
    this.emit(McpAppsServiceEvent.ToolCancelled, {
      toolKey,
      toolCallId,
    } satisfies McpAppsToolCancelledEvent);
  }

  /**
   * Clear all cached resources and connections, re-run discovery, and
   * emit DiscoveryComplete so the renderer refetches everything.
   * Intended for developer debugging via the File > Developer menu.
   */
  async refreshDiscovery(): Promise<void> {
    this.log.info("refreshDiscovery: clearing caches and re-running discovery");

    // Close existing connections
    for (const [, conn] of this.connections) {
      await conn.client.close().catch(() => {});
    }
    this.connections.clear();
    this.resourceCache.clear();
    this.resourceMetaCache.clear();
    this.toolAssociations.clear();
    this.toolDefinitions.clear();
    this.pendingConnections.clear();
    this.pendingFetches.clear();

    // Re-discover using stored server configs
    const serverNames = [...this.serverConfigs.keys()];
    if (serverNames.length > 0) {
      await this.handleDiscovery(serverNames);
    } else {
      this.log.warn(
        "refreshDiscovery: no server configs stored, nothing to discover",
      );
    }
  }

  async disconnectServer(serverName: string): Promise<void> {
    const conn = this.connections.get(serverName);
    if (!conn) return;

    try {
      await conn.client.close();
    } catch (err) {
      this.log.warn("Error closing MCP connection", {
        serverName,
        error: err instanceof Error ? err.message : String(err),
      });
    }
    this.connections.delete(serverName);

    // Clean up associations and cached resources for this server
    const urisToEvict = new Set<string>();
    for (const [key, assoc] of this.toolAssociations) {
      if (assoc.serverName === serverName) {
        urisToEvict.add(assoc.resourceUri);
        this.toolAssociations.delete(key);
      }
    }

    // Only evict cached resources not referenced by remaining associations
    const stillReferenced = new Set(
      [...this.toolAssociations.values()].map((a) => a.resourceUri),
    );
    for (const uri of urisToEvict) {
      if (!stillReferenced.has(uri)) {
        this.resourceCache.delete(uri);
      }
    }
  }

  async cleanup(): Promise<void> {
    const serverNames = [...this.connections.keys()];
    for (const name of serverNames) {
      await this.disconnectServer(name);
    }
    this.resourceCache.clear();
    this.resourceMetaCache.clear();
    this.toolAssociations.clear();
    this.toolDefinitions.clear();
    this.serverConfigs.clear();
    this.pendingConnections.clear();
    this.pendingFetches.clear();
  }
}
