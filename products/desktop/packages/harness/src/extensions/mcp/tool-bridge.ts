/**
 * Tool bridge: converts MCP tools into pi tools and manages their lifecycle.
 *
 *   - Paginated tools/list (cursor loop per spec, with a max-page guard)
 *   - JSON Schema → TypeBox conversion (see ./schema.ts)
 *   - Tool name sanitization: `<prefix>_<server>_<tool>`, [a-zA-Z0-9_], ≤64 chars
 *   - Tool annotations surfaced as description hints
 *   - AbortSignal propagation → SDK sends notifications/cancelled
 *   - Register-once + activate/deactivate as servers connect/disconnect
 *   - Text/image passthrough; audio/resource content described as text
 */

import {
  DEFAULT_MAX_BYTES,
  DEFAULT_MAX_LINES,
  type ExtensionAPI,
  formatSize,
  truncateHead,
} from "@earendil-works/pi-coding-agent";
import type { Client } from "@modelcontextprotocol/sdk/client/index.js";
import {
  CallToolResultSchema,
  ListToolsResultSchema,
} from "@modelcontextprotocol/sdk/types.js";
import type { McpServerConfig, McpSettings } from "./config";
import { McpError } from "./errors";
import { renderMcpToolCall } from "./render";
import { convertJsonSchemaToTypebox } from "./schema";
import { hashServerConfig, type McpToolCache } from "./tool-cache";

/** Subset of pi's ExtensionAPI the bridge needs (narrow for easy faking). */
export type ToolBridgeHost = Pick<
  ExtensionAPI,
  "registerTool" | "getActiveTools" | "setActiveTools"
>;

const MAX_TOOL_NAME_LENGTH = 64;
const MAX_LIST_PAGES = 100;

/**
 * Build a pi-compatible tool name: `<prefix>_<server>_<tool>`.
 * Sanitized to [a-zA-Z0-9_]. Names longer than 64 chars are truncated with a
 * short hash suffix so distinct long names cannot collide after truncation.
 */
export function buildToolName(
  prefix: string,
  serverName: string,
  toolName: string,
): string {
  const raw = `${prefix}_${serverName}_${toolName}`;
  const safe = raw.replace(/[^a-zA-Z0-9_]/g, "_");
  if (safe.length <= MAX_TOOL_NAME_LENGTH) return safe;
  const hash = Math.abs(
    [...safe].reduce((acc, c) => ((acc << 5) - acc + c.charCodeAt(0)) | 0, 0),
  )
    .toString(36)
    .slice(0, 8);
  return `${safe.slice(0, MAX_TOOL_NAME_LENGTH - hash.length - 1)}_${hash}`;
}

export type BridgedContent =
  | { type: "text"; text: string }
  | { type: "image"; data: string; mimeType: string };

/** Convert MCP tool-result content blocks into pi tool-result content. */
export function convertMcpContent(items: unknown[]): BridgedContent[] {
  return items.map((raw): BridgedContent => {
    if (!raw || typeof raw !== "object") {
      return { type: "text", text: String(raw) };
    }
    const item = raw as Record<string, unknown>;
    switch (item.type) {
      case "text":
        return { type: "text", text: String(item.text ?? "") };
      case "image":
        if (
          typeof item.data === "string" &&
          typeof item.mimeType === "string"
        ) {
          return { type: "image", data: item.data, mimeType: item.mimeType };
        }
        return { type: "text", text: "[Image: invalid payload]" };
      case "audio":
        return {
          type: "text",
          text: `[Audio: ${String(item.mimeType ?? "unknown")}, base64 encoded]`,
        };
      case "resource": {
        const resource = item.resource as Record<string, unknown> | undefined;
        if (typeof resource?.text === "string") {
          return { type: "text", text: resource.text };
        }
        if (resource?.blob) {
          return {
            type: "text",
            text: `[Resource blob: ${String(resource.uri ?? "unknown")}]`,
          };
        }
        return {
          type: "text",
          text: `[Resource: ${String(resource?.uri ?? "unknown")}]`,
        };
      }
      default:
        return { type: "text", text: JSON.stringify(item) };
    }
  });
}

export interface McpToolDefinition {
  name: string;
  description?: string;
  inputSchema: Record<string, unknown>;
  annotations?: {
    readOnlyHint?: boolean;
    destructiveHint?: boolean;
    idempotentHint?: boolean;
    openWorldHint?: boolean;
    title?: string;
  };
}

/**
 * Fetch all tools from a server using cursor-based pagination. The MCP spec
 * mandates that clients follow `nextCursor` until exhausted; a max-page guard
 * protects against broken servers that loop forever.
 */
export async function listAllTools(
  client: Client,
  requestTimeoutMs: number,
): Promise<McpToolDefinition[]> {
  const tools: McpToolDefinition[] = [];
  let cursor: string | undefined;
  let pages = 0;

  do {
    if (pages >= MAX_LIST_PAGES) break;
    const result = await client.request(
      { method: "tools/list", params: cursor ? { cursor } : {} },
      ListToolsResultSchema,
      { timeout: requestTimeoutMs },
    );
    tools.push(...(result.tools as McpToolDefinition[]));
    cursor = result.nextCursor;
    pages++;
  } while (cursor);

  return tools;
}

function buildDescription(tool: McpToolDefinition): string {
  let description = tool.description ?? `MCP tool: ${tool.name}`;
  const ann = tool.annotations;
  if (ann) {
    const hints: string[] = [];
    if (ann.readOnlyHint) hints.push("read-only");
    if (ann.destructiveHint) hints.push("destructive");
    if (ann.idempotentHint) hints.push("idempotent");
    if (ann.openWorldHint) hints.push("interacts with external systems");
    if (hints.length > 0) description += ` [${hints.join(", ")}]`;
  }
  return description;
}

export interface ToolCollision {
  serverName: string;
  mcpToolName: string;
  piToolName: string;
}

/** Metadata the `mcp` proxy tool needs to search over and dispatch calls. */
export interface ToolMeta {
  serverName: string;
  mcpName: string;
  description: string;
}

export interface SearchableTool extends ToolMeta {
  piName: string;
  /** Whether this tool is currently in the model's active tool set. */
  active: boolean;
}

/**
 * Call an MCP tool and convert the result into pi tool-result content.
 * Shared by directly-registered pi tools (`ToolBridge.registerTool`) and the
 * `mcp` proxy tool, so both paths get identical error handling.
 */
/**
 * Truncate each text content block to pi's built-in-tool convention (50KB /
 * 2000 lines, whichever hits first — see `DEFAULT_MAX_BYTES`/
 * `DEFAULT_MAX_LINES`). Render-level collapsing (render.ts) only affects
 * what the TUI *displays*; without this, an MCP tool that returns a large
 * result (e.g. a broad SQL query) would send it to the model uncapped —
 * the same class of context blowup as an untruncated discovery dump, just
 * via the actual call path instead.
 */
export function truncateBridgedContent(
  content: BridgedContent[],
): BridgedContent[] {
  return content.map((item): BridgedContent => {
    if (item.type !== "text") return item;
    const truncation = truncateHead(item.text, {
      maxLines: DEFAULT_MAX_LINES,
      maxBytes: DEFAULT_MAX_BYTES,
    });
    if (!truncation.truncated) return item;
    const note =
      `\n\n[Output truncated: ${truncation.outputLines} of ${truncation.totalLines} lines ` +
      `(${formatSize(truncation.outputBytes)} of ${formatSize(truncation.totalBytes)}). ` +
      `Narrow the query/arguments (filters, LIMIT, pagination) to see more.]`;
    return { type: "text", text: truncation.content + note };
  });
}

export async function invokeTool(
  client: Client,
  serverName: string,
  mcpToolName: string,
  args: Record<string, unknown>,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<{ content: BridgedContent[] }> {
  if (signal?.aborted) {
    return { content: [{ type: "text", text: "Cancelled" }] };
  }
  try {
    const result = await client.request(
      { method: "tools/call", params: { name: mcpToolName, arguments: args } },
      CallToolResultSchema,
      // The SDK sends notifications/cancelled when the signal fires.
      { timeout: timeoutMs, ...(signal ? { signal } : {}) },
    );

    const content = truncateBridgedContent(
      convertMcpContent(result.content as unknown[]),
    );

    // Tool execution errors (isError) are distinct from protocol errors.
    if (result.isError) {
      const text = content
        .map((c) => (c.type === "text" ? c.text : `[${c.type}]`))
        .join("\n");
      throw new McpError(text || "Tool reported an error", serverName, "tool");
    }

    return { content };
  } catch (err) {
    if (err instanceof McpError) throw err;
    throw new McpError(
      err instanceof Error ? err.message : String(err),
      serverName,
      "protocol",
      err,
    );
  }
}

export interface ToolBridgeOptions {
  /** Disk-backed metadata cache, used so `mcp` search works pre-connection. */
  toolCache?: McpToolCache;
  /**
   * Called after every tool call (direct or via the `mcp` proxy tool), so
   * lazy-server idle timeouts reset on real use.
   */
  onToolUsed?: (serverName: string) => void;
}

/**
 * Manages MCP tools as pi tools for a set of servers. Tools are (re-)registered
 * on every refresh (pi's `registerTool` overwrites by name, and re-registering
 * rebinds the execute closure to the latest client after reconnects). Only
 * `directTools`/proxy-activated tools are ever put in the model's active set
 * (`setActiveTools`) — the rest stay registered-but-inactive so their schemas
 * don't cost context until the `mcp` proxy tool activates them.
 */
export class ToolBridge {
  private readonly settings: McpSettings;
  private readonly pi: ToolBridgeHost;
  private readonly toolCache: McpToolCache | undefined;
  private readonly onToolUsed: ((serverName: string) => void) | undefined;
  /** pi tool names registered per MCP server. */
  private readonly serverToolNames = new Map<string, Set<string>>();
  /** Collisions observed during each server's most recent refresh. */
  private readonly serverCollisions = new Map<string, ToolCollision[]>();
  /** Metadata for every currently-registered pi tool (active or not). */
  private readonly toolMeta = new Map<string, ToolMeta>();
  /** Per-server pi names that `directTools` config puts straight in context. */
  private readonly serverDirectNames = new Map<string, Set<string>>();
  /**
   * Per-server pi names activated on demand via the `mcp` proxy tool's
   * search+call flow. Tracked separately from pi's active-tools list so a
   * reconnect can restore them (activateServer/deactivateServer otherwise
   * only know about `directTools`).
   */
  private readonly serverSearchActivated = new Map<string, Set<string>>();

  constructor(
    settings: McpSettings,
    pi: ToolBridgeHost,
    options: ToolBridgeOptions = {},
  ) {
    this.settings = settings;
    this.pi = pi;
    this.toolCache = options.toolCache;
    this.onToolUsed = options.onToolUsed;
  }

  /** pi tool names currently tracked for a server. */
  getToolNames(serverName: string): string[] {
    return [...(this.serverToolNames.get(serverName) ?? [])];
  }

  /** Name collisions from the server's most recent refresh (for `/mcp <name>`). */
  getCollisions(serverName: string): ToolCollision[] {
    return [...(this.serverCollisions.get(serverName) ?? [])];
  }

  /** Whether `piName` is currently registered (from any connected server). */
  hasTool(piName: string): boolean {
    return this.toolMeta.has(piName);
  }

  /** Metadata for a registered pi tool, for the `mcp` proxy tool's dispatch. */
  getToolMeta(piName: string): ToolMeta | undefined {
    return this.toolMeta.get(piName);
  }

  /** All currently-registered tools, for the `mcp` proxy tool's search. */
  getSearchableTools(): SearchableTool[] {
    const active = new Set(this.pi.getActiveTools());
    return [...this.toolMeta.entries()].map(([piName, meta]) => ({
      piName,
      ...meta,
      active: active.has(piName),
    }));
  }

  /**
   * Activate specific pi tool names on demand (the `mcp` proxy tool's
   * `tool` call). Only known tool names are activated; unknown names are
   * silently skipped (the proxy tool validates before calling this).
   * Remembered per-server so a later reconnect restores them.
   */
  activateTools(piNames: readonly string[]): string[] {
    const activated: string[] = [];
    const active = new Set(this.pi.getActiveTools());
    for (const piName of piNames) {
      const meta = this.toolMeta.get(piName);
      if (!meta || active.has(piName)) continue;
      active.add(piName);
      activated.push(piName);
      const set = this.serverSearchActivated.get(meta.serverName) ?? new Set();
      set.add(piName);
      this.serverSearchActivated.set(meta.serverName, set);
    }
    if (activated.length > 0) this.pi.setActiveTools([...active]);
    return activated;
  }

  /**
   * Refresh tools for a server — called on initial connect and on
   * notifications/tools/list_changed. Deactivates tools that disappeared
   * from the server's list, then activates the current set.
   *
   * `requestTimeoutMs` overrides the global default (per-server config).
   * `serverConfig`, when given, drives `directTools` filtering and the
   * on-disk metadata cache used by the `mcp` proxy tool's search.
   */
  async refreshTools(
    serverName: string,
    client: Client,
    requestTimeoutMs?: number,
    serverConfig?: McpServerConfig,
  ): Promise<void> {
    const timeoutMs = requestTimeoutMs ?? this.settings.requestTimeoutMs;

    let tools: McpToolDefinition[];
    try {
      tools = await listAllTools(client, timeoutMs);
    } catch (err) {
      throw new McpError(
        `Failed to list tools: ${err instanceof Error ? err.message : String(err)}`,
        serverName,
        "protocol",
        err,
      );
    }

    const previous = this.serverToolNames.get(serverName) ?? new Set<string>();
    const current = new Set<string>();
    // First MCP tool name to claim each pi name, so a collision report shows
    // both sides of the conflict, not just the tool that won the shadowing.
    const firstClaimant = new Map<string, string>();
    const reportedClaimant = new Set<string>();
    const collisions: ToolCollision[] = [];
    const directConfig = serverConfig?.directTools ?? true;
    const directNames = new Set<string>();

    for (const tool of tools) {
      const piName = buildToolName(
        this.settings.toolPrefix,
        serverName,
        tool.name,
      );
      const claimant = firstClaimant.get(piName);
      if (claimant !== undefined) {
        // Two MCP tools sanitize to the same pi name (e.g. "a-b" vs "a_b").
        // The later definition wins; both names are recorded for /mcp
        // <name> diagnostics so the shadowed tool isn't invisible.
        if (!reportedClaimant.has(piName)) {
          reportedClaimant.add(piName);
          collisions.push({
            serverName,
            mcpToolName: claimant,
            piToolName: piName,
          });
        }
        collisions.push({
          serverName,
          mcpToolName: tool.name,
          piToolName: piName,
        });
      } else {
        firstClaimant.set(piName, tool.name);
      }
      current.add(piName);
      const description = this.registerTool(
        piName,
        serverName,
        tool,
        client,
        timeoutMs,
      );
      this.toolMeta.set(piName, {
        serverName,
        mcpName: tool.name,
        description,
      });
      const isDirect =
        directConfig === true ||
        (Array.isArray(directConfig) && directConfig.includes(tool.name));
      if (isDirect) directNames.add(piName);
    }

    for (const stale of previous) {
      if (!current.has(stale)) {
        this.deactivateTool(stale);
        this.toolMeta.delete(stale);
      }
    }
    const searchActivated = this.serverSearchActivated.get(serverName);
    if (searchActivated) {
      for (const name of searchActivated) {
        if (!current.has(name)) searchActivated.delete(name);
      }
    }

    this.serverToolNames.set(serverName, current);
    this.serverCollisions.set(serverName, collisions);
    this.serverDirectNames.set(serverName, directNames);
    this.activateServer(serverName);

    if (this.toolCache && serverConfig) {
      const entry = {
        configHash: hashServerConfig(serverConfig),
        ...(serverConfig.description !== undefined
          ? { description: serverConfig.description }
          : {}),
        tools: tools.map((tool) => ({
          name: buildToolName(this.settings.toolPrefix, serverName, tool.name),
          mcpName: tool.name,
          description: buildDescription(tool),
        })),
      };
      void this.toolCache.set(serverName, entry).catch(() => {
        // Best effort — a failed cache write only degrades pre-connection search.
      });
    }
  }

  /**
   * Activate this server's `directTools` and any proxy-activated tools —
   * deactivating the rest of its tools. Must always reconcile (never
   * early-return when there's nothing to *add*): pi's own `registerTool()`
   * auto-activates every brand-new tool name the moment it's registered
   * (`agent-session.js` `_refreshToolRegistry`), so a server with
   * `directTools: false` still needs its tools explicitly pulled back out
   * of the active set here, or they silently stay in context.
   */
  activateServer(serverName: string): void {
    const names = this.serverToolNames.get(serverName);
    if (!names || names.size === 0) return;
    const direct = this.serverDirectNames.get(serverName);
    const extra = this.serverSearchActivated.get(serverName);
    const shouldBeActive = (name: string) =>
      direct?.has(name) || extra?.has(name);
    const active = new Set(this.pi.getActiveTools());
    for (const name of names) {
      if (shouldBeActive(name)) active.add(name);
      else active.delete(name);
    }
    this.pi.setActiveTools([...active]);
  }

  /** Deactivate all pi tools belonging to a server (on disconnect). */
  deactivateServer(serverName: string): void {
    const names = this.serverToolNames.get(serverName);
    if (!names || names.size === 0) return;
    this.pi.setActiveTools(
      this.pi.getActiveTools().filter((name) => !names.has(name)),
    );
  }

  private deactivateTool(piName: string): void {
    this.pi.setActiveTools(
      this.pi.getActiveTools().filter((name) => name !== piName),
    );
  }

  /** Registers the pi tool and returns its (annotation-augmented) description. */
  private registerTool(
    piName: string,
    serverName: string,
    tool: McpToolDefinition,
    client: Client,
    timeoutMs: number,
  ): string {
    const description = buildDescription(tool);
    const onToolUsed = this.onToolUsed;

    this.pi.registerTool({
      name: piName,
      label: tool.annotations?.title ?? tool.name,
      description,
      parameters: convertJsonSchemaToTypebox(tool.inputSchema),

      renderCall(args, theme, context) {
        return renderMcpToolCall(piName, args, theme, context.expanded);
      },

      async execute(_toolCallId, params, signal) {
        onToolUsed?.(serverName);
        const { content } = await invokeTool(
          client,
          serverName,
          tool.name,
          (params ?? {}) as Record<string, unknown>,
          timeoutMs,
          signal,
        );
        return { content, details: {} };
      },
    });
    return description;
  }
}
