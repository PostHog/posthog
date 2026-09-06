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
import { parseMcpToolName, TypedEventEmitter } from "@posthog/shared";
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
  type McpToolUiVisibility,
  type McpUiResource,
  resolveResultResourceUri,
  resolveToolRegistrationMetadata,
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
const MAX_DISCOVERY_PAGES = 100;
const DISCOVERY_FAILURE_BACKOFF_MS = 60_000;

interface ServerConnection {
  name: string;
  client: Client;
  transport: StreamableHTTPClientTransport;
}

class MissingMcpServerConfigError extends Error {}

@injectable()
export class McpAppsService extends TypedEventEmitter<McpAppsServiceEvents> {
  private connections = new Map<string, ServerConnection>();
  private resourceCache = new Map<string, McpUiResource>();
  private toolAssociations = new Map<string, McpToolUiAssociation>();
  private toolDefinitions = new Map<string, Tool>();
  private toolVisibilities = new Map<string, McpToolUiVisibility[]>();
  private serverToolKeys = new Map<string, Set<string>>();
  private serverConfigs = new Map<string, McpServerConnectionConfig>();
  private configResolver?: (serverName: string) => Promise<void>;
  private pendingConnections = new Map<string, Promise<ServerConnection>>();
  private pendingFetches = new Map<string, Promise<McpUiResource | null>>();
  private resourceMetaCache = new Map<string, McpResourceUiMeta>();
  private discoveredServers = new Set<string>();
  private unavailableServers = new Set<string>();
  private pendingDiscoveries = new Map<string, Promise<void>>();
  private discoveryFailedAt = new Map<string, number>();
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

  // Two servers can serve different content at the same ui:// URI, so every
  // per-resource cache (resource, meta, pending fetch) keys on server + URI.
  private resourceKey(serverName: string, resourceUri: string): string {
    return `${serverName}\n${resourceUri}`;
  }

  private evictServerEntries<T>(map: Map<string, T>, serverName: string): void {
    const keyPrefix = this.resourceKey(serverName, "");
    for (const key of map.keys()) {
      if (key.startsWith(keyPrefix)) {
        map.delete(key);
      }
    }
  }

  private clearServerDiscoveryData(serverName: string): void {
    const toolKeys = this.serverToolKeys.get(serverName);
    if (toolKeys) {
      for (const toolKey of toolKeys) {
        this.toolAssociations.delete(toolKey);
        this.toolDefinitions.delete(toolKey);
        this.toolVisibilities.delete(toolKey);
      }
    }
    this.serverToolKeys.delete(serverName);
    this.evictServerEntries(this.resourceCache, serverName);
    this.evictServerEntries(this.resourceMetaCache, serverName);
  }

  /**
   * Store server configs for lazy connections later.
   * No connections are created at this point.
   */
  setServerConfigs(configs: McpServerConnectionConfig[]): void {
    this.serverConfigs.clear();
    this.unavailableServers.clear();
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
      this.unavailableServers.delete(config.name);
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
    const names = serverNames.filter((name) => this.serverConfigs.has(name));
    const results = await Promise.allSettled(
      names.map((name) => this.discoverServer(name)),
    );
    results.forEach((result, i) => {
      if (result.status === "rejected") {
        this.log.warn("Failed to discover UI tools for server", {
          serverName: names[i],
          error:
            result.reason instanceof Error
              ? result.reason.message
              : String(result.reason),
        });
      }
    });

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

  private async listAllTools(
    client: Client,
    serverName: string,
  ): Promise<Tool[]> {
    const tools: Tool[] = [];
    let cursor: string | undefined;

    for (let page = 0; page < MAX_DISCOVERY_PAGES; page++) {
      const result = await client.listTools(cursor ? { cursor } : undefined);
      tools.push(...result.tools);
      cursor = result.nextCursor;
      if (!cursor) return tools;
    }

    this.log.warn("Tool discovery reached the page limit", {
      serverName,
      pageLimit: MAX_DISCOVERY_PAGES,
    });
    return tools;
  }

  private async listAllResources(
    client: Client,
    serverName: string,
  ): Promise<McpResourceUiMeta[]> {
    const resources: McpResourceUiMeta[] = [];
    let cursor: string | undefined;

    for (let page = 0; page < MAX_DISCOVERY_PAGES; page++) {
      const result = await client.listResources(
        cursor ? { cursor } : undefined,
      );
      resources.push(...(result.resources as McpResourceUiMeta[]));
      cursor = result.nextCursor;
      if (!cursor) return resources;
    }

    this.log.warn("Resource discovery reached the page limit", {
      serverName,
      pageLimit: MAX_DISCOVERY_PAGES,
    });
    return resources;
  }

  /**
   * Connect to a single server and discover tool and resource metadata. The
   * connection stays open for proxy calls, resource reads, and HTML fetches.
   */
  private async discoverServerUiTools(serverName: string): Promise<void> {
    const conn = await this.getOrCreateConnection(serverName);

    const [tools, resources] = await Promise.all([
      this.listAllTools(conn.client, serverName),
      this.listAllResources(conn.client, serverName).catch((err) => {
        this.log.warn("listResources failed during discovery", {
          serverName,
          error: err instanceof Error ? err.message : String(err),
        });
        return null;
      }),
    ]);

    this.log.info("discoverServerUiTools: listed tools", {
      serverName,
      toolNames: tools.map((tool) => tool.name),
      hasExecTool:
        serverName === BUILTIN_POSTHOG_SERVER_NAME &&
        tools.some((tool) => tool.name === EXEC_TOOL_NAME),
      resourceUris: resources?.map((resource) => resource.uri),
    });

    this.clearServerDiscoveryData(serverName);
    const serverToolKeys = new Set<string>();

    for (const tool of tools) {
      const toolKey = `mcp__${serverName}__${tool.name}`;
      const { resourceUri, visibility } = resolveToolRegistrationMetadata(tool);

      serverToolKeys.add(toolKey);
      this.toolDefinitions.set(toolKey, tool);
      this.toolVisibilities.set(toolKey, visibility);

      if (!resourceUri) continue;
      if (!resourceUri.startsWith("ui://")) {
        this.log.warn("Ignoring MCP App tool with a non-ui resource URI", {
          serverName,
          toolName: tool.name,
          resourceUri,
        });
        continue;
      }

      this.toolAssociations.set(toolKey, {
        toolKey,
        serverName,
        toolName: tool.name,
        resourceUri,
        visibility,
      });
    }
    this.serverToolKeys.set(serverName, serverToolKeys);

    // Cache resource metadata because some servers omit it from read responses.
    if (resources) {
      for (const resource of resources) {
        if (resource._meta?.ui) {
          this.resourceMetaCache.set(
            this.resourceKey(serverName, resource.uri),
            resource,
          );
        }
      }
    }
  }

  /**
   * Run discovery for one server, deduplicating concurrent attempts. Always
   * lists fresh (no discovered-cache short-circuit) so session starts pick up
   * server-side tool changes.
   */
  private discoverServer(serverName: string): Promise<void> {
    const pending = this.pendingDiscoveries.get(serverName);
    if (pending) return pending;

    const discovery = (async () => {
      try {
        await this.discoverServerUiTools(serverName);
        this.discoveredServers.add(serverName);
        this.discoveryFailedAt.delete(serverName);
      } catch (err) {
        this.discoveryFailedAt.set(serverName, Date.now());
        throw err;
      } finally {
        this.pendingDiscoveries.delete(serverName);
      }
    })();
    this.pendingDiscoveries.set(serverName, discovery);
    return discovery;
  }

  /**
   * Lazily discover a server's UI tools on first use. Cloud runs never start a
   * local agent session, so handleDiscovery never fires for them and the
   * association map stays empty — the review-card path then fails silently.
   * Failures rethrow (with a short backoff against hammering the config
   * resolver) so callers' queries surface an error and retry instead of
   * caching a permanent miss.
   */
  private async ensureServerDiscovered(serverName: string): Promise<boolean> {
    if (this.discoveredServers.has(serverName)) return true;
    if (this.unavailableServers.has(serverName)) return false;

    // Only the caller that starts the discovery emits DiscoveryComplete —
    // joiners would otherwise re-emit once per caller and stampede the
    // renderer's query invalidations.
    const startedHere = !this.pendingDiscoveries.has(serverName);
    if (startedHere) {
      const failedAt = this.discoveryFailedAt.get(serverName);
      if (failedAt && Date.now() - failedAt < DISCOVERY_FAILURE_BACKOFF_MS) {
        throw new Error(`UI tool discovery recently failed for: ${serverName}`);
      }
    }

    try {
      await this.discoverServer(serverName);
    } catch (error) {
      if (!(error instanceof MissingMcpServerConfigError)) throw error;
      // Historical cloud runs can contain tools from servers that are not
      // configured in this Desktop process. They simply have no local custom
      // UI; remember that until the server configuration changes.
      this.unavailableServers.add(serverName);
      this.discoveryFailedAt.delete(serverName);
      this.log.debug("Skipping UI discovery for unavailable MCP server", {
        serverName,
      });
      return false;
    }
    if (startedHere) {
      this.emit(McpAppsServiceEvent.DiscoveryComplete, {
        toolKeys: [...this.toolAssociations.keys()],
      } satisfies McpAppsDiscoveryCompleteEvent);
    }
    return true;
  }

  /**
   * Look up a tool's UI association, lazily discovering its server on a miss.
   */
  private async resolveAssociation(
    toolKey: string,
  ): Promise<McpToolUiAssociation | undefined> {
    const existing = this.toolAssociations.get(toolKey);
    if (existing) return existing;
    const mcp = parseMcpToolName(toolKey);
    if (!mcp) return undefined;
    await this.ensureServerDiscovered(mcp.server);
    return this.toolAssociations.get(toolKey);
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
      throw new MissingMcpServerConfigError(
        `No server config for: ${serverName}`,
      );
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
    const association = await this.resolveAssociation(toolKey);
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
    if (!resourceUri.startsWith("ui://")) {
      this.log.warn("Rejecting executable MCP App resource with a non-ui URI", {
        serverName,
        resourceUri,
      });
      return null;
    }

    const key = this.resourceKey(serverName, resourceUri);
    const cached = this.resourceCache.get(key);
    if (cached) {
      this.log.debug("fetchUiResourceByUri: cache hit", {
        serverName,
        resourceUri,
      });
      return cached;
    }

    const pendingFetch = this.pendingFetches.get(key);
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
    this.pendingFetches.set(key, fetchPromise);
    try {
      return await fetchPromise;
    } finally {
      this.pendingFetches.delete(key);
    }
  }

  private async doFetchUiResource(
    serverName: string,
    resourceUri: string,
  ): Promise<McpUiResource | null> {
    // Best-effort warm of resourceMetaCache so CSP/permissions attach on paths
    // where handleDiscovery never ran (cloud runs fetching by result URI). The
    // read below decides success on its own.
    const warmed = await this.ensureServerDiscovered(serverName).then(
      (discovered) => discovered,
      (err) => {
        this.log.warn("UI resource metadata warm-up failed", {
          serverName,
          uri: resourceUri,
          error: err instanceof Error ? err.message : String(err),
        });
        return false;
      },
    );

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

    const resourceMeta = this.resourceMetaCache.get(
      this.resourceKey(serverName, resourceUri),
    );
    // Read-response ui.csp/ui.permissions win; the listing-derived cache is a
    // fallback for servers that only advertise them at registration.
    const readUi = (textContent as { _meta?: McpResourceUiMeta["_meta"] })._meta
      ?.ui;
    const listUi = resourceMeta?._meta?.ui;
    const csp = readUi?.csp ?? listUi?.csp;
    const permissions = readUi?.permissions ?? listUi?.permissions;

    const resource: McpUiResource = {
      uri: resourceUri,
      name: resourceMeta?.name,
      mimeType: UI_MIME_TYPE,
      csp,
      permissions,
      html: textContent.text,
      serverName,
    };

    // A failed warm-up with no known metadata may have produced a CSP-less
    // copy; leave it uncached so a later fetch can attach the real CSP.
    const cacheable =
      warmed ||
      resourceMeta !== undefined ||
      csp !== undefined ||
      permissions !== undefined;
    if (cacheable) {
      this.resourceCache.set(
        this.resourceKey(serverName, resourceUri),
        resource,
      );
    }
    this.log.info("Lazily fetched UI resource", {
      serverName,
      uri: resourceUri,
      htmlLength: textContent.text.length,
      hasCsp: !!resource.csp,
      cached: cacheable,
    });

    return resource;
  }

  async hasUiForTool(toolKey: string): Promise<boolean> {
    const has = !!(await this.resolveAssociation(toolKey));
    this.log.debug("hasUiForTool", { toolKey, result: has });
    return has;
  }

  async getToolDefinition(toolKey: string): Promise<Tool | null> {
    const existing = this.toolDefinitions.get(toolKey);
    if (existing) return existing;

    const mcp = parseMcpToolName(toolKey);
    if (!mcp) return null;
    await this.ensureServerDiscovered(mcp.server);
    return this.toolDefinitions.get(toolKey) ?? null;
  }

  async proxyToolCall(
    serverName: string,
    toolName: string,
    args?: Record<string, unknown>,
  ): Promise<unknown> {
    await this.ensureServerDiscovered(serverName);

    const toolKey = `mcp__${serverName}__${toolName}`;
    if (!this.toolDefinitions.has(toolKey)) {
      throw new Error(`Tool "${toolName}" is not available to apps`);
    }

    const visibility = this.toolVisibilities.get(toolKey);
    if (!visibility?.includes("app")) {
      throw new Error(
        `Tool "${toolName}" is not accessible to apps (visibility: ${visibility?.join(", ") ?? "unknown"})`,
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
    // Arbitrary schemes stay confined to the app's captured MCP server.
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
    this.toolVisibilities.clear();
    this.serverToolKeys.clear();
    this.pendingConnections.clear();
    this.pendingFetches.clear();
    this.discoveredServers.clear();
    this.unavailableServers.clear();
    this.pendingDiscoveries.clear();
    this.discoveryFailedAt.clear();

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
    // Let an in-flight lazy discovery land its connection first so it is
    // closed here instead of lingering as a stray reconnect after teardown.
    const pendingDiscovery = this.pendingDiscoveries.get(serverName);
    if (pendingDiscovery) {
      await pendingDiscovery.catch(() => undefined);
    }

    this.discoveredServers.delete(serverName);
    this.unavailableServers.delete(serverName);
    this.discoveryFailedAt.delete(serverName);
    this.clearServerDiscoveryData(serverName);

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
  }

  async cleanup(): Promise<void> {
    // Include servers whose lazy discovery is still connecting — they have no
    // entry in `connections` yet but will land one that must be closed.
    const serverNames = new Set([
      ...this.connections.keys(),
      ...this.pendingDiscoveries.keys(),
    ]);
    for (const name of serverNames) {
      await this.disconnectServer(name);
    }
    this.resourceCache.clear();
    this.resourceMetaCache.clear();
    this.toolAssociations.clear();
    this.toolDefinitions.clear();
    this.toolVisibilities.clear();
    this.serverToolKeys.clear();
    this.serverConfigs.clear();
    this.pendingConnections.clear();
    this.pendingFetches.clear();
    this.discoveredServers.clear();
    this.unavailableServers.clear();
    this.pendingDiscoveries.clear();
    this.discoveryFailedAt.clear();
  }
}
