/**
 * The `mcp` proxy tool: a single, cheap (~200 token) tool that lets the
 * model search for and call MCP tools without every server's full schema
 * catalog sitting in context (see ToolBridge's `directTools` gating) and
 * without every `lifecycle: "lazy"` server having to be connected up front
 * (see ServerManager's on-demand start below).
 *
 *   mcp({ search: "keywords" })   — find relevant tools/servers, connected
 *                                   or not (cached metadata covers the
 *                                   latter without dialing them).
 *   mcp({ tool: "name", args })   — call a tool by exact name, or a server
 *                                   name to connect + discover its tools.
 *                                   Starts the owning server on demand.
 */

import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import type { McpSettings } from "./config";
import { describeError } from "./errors";
import { renderMcpProxyCall, renderMcpProxyResult } from "./render";
import type { ManagedServer, ServerManager } from "./server-manager";
import {
  type BridgedContent,
  invokeTool,
  type SearchableTool,
  type ToolBridge,
} from "./tool-bridge";
import type { McpToolCache } from "./tool-cache";

export interface ProxyToolDeps {
  getManager: () => ServerManager | null;
  getBridge: () => ToolBridge | null;
  getToolCache: () => McpToolCache | null;
  getSettings: () => McpSettings | null;
  getCwd: () => string;
  /** Appends an `/mcp:auth <server>` hint to auth-required error messages. */
  authHint: (serverName: string, message: string) => string;
}

export interface Hit {
  /** Exact pi tool name to call, if known (live or cached). Absent = server-only hit. */
  piName?: string;
  serverName: string;
  description: string;
  connected: boolean;
  score: number;
}

/**
 * Structured detail alongside the text `content`, so `renderCall`/
 * `renderResult` can render nicely without re-parsing the text (which is
 * written for the model, not the terminal).
 */
export type McpProxyDetails =
  | { kind: "no-config" }
  | { kind: "usage" }
  | { kind: "error"; message: string }
  | { kind: "search"; query: string; hits: Hit[] }
  | { kind: "connect"; server: string; toolCount: number }
  | { kind: "call"; server: string; tool: string; piName: string };

function normalize(s: string): string {
  return s.toLowerCase().replace(/[-_]/g, " ");
}

function terms(query: string): string[] {
  return normalize(query).split(/\s+/).filter(Boolean);
}

/** OR-match: score = number of distinct query terms found in `haystack`. */
function score(queryTerms: string[], haystack: string): number {
  const norm = normalize(haystack);
  let n = 0;
  for (const term of queryTerms) if (norm.includes(term)) n++;
  return n;
}

async function search(
  manager: ServerManager,
  bridge: ToolBridge,
  toolCache: McpToolCache | null,
  limit: number,
  query: string,
): Promise<Hit[]> {
  const queryTerms = terms(query);
  const hits = new Map<string, Hit>();

  const live: SearchableTool[] = bridge.getSearchableTools();
  for (const tool of live) {
    const s = score(
      queryTerms,
      `${tool.piName} ${tool.mcpName} ${tool.description} ${tool.serverName}`,
    );
    if (s > 0) {
      hits.set(tool.piName, {
        piName: tool.piName,
        serverName: tool.serverName,
        description: truncateDescription(tool.description),
        connected: true,
        score: s,
      });
    }
  }

  const servers: ManagedServer[] = manager.getAllServers();
  // One read of the whole cache file up front, not one per non-ready
  // server — `McpToolCache.get` re-reads the entire file from disk each
  // call, so looping `get()` here would issue N redundant reads of the
  // exact same file for N non-ready servers.
  const cachedAll = toolCache ? await toolCache.all() : {};
  for (const server of servers) {
    if (server.state === "ready") continue; // already covered by `live` above
    const cached = cachedAll[server.name];
    if (cached) {
      for (const tool of cached.tools) {
        if (hits.has(tool.name)) continue;
        const s = score(
          queryTerms,
          `${tool.name} ${tool.mcpName} ${tool.description} ${server.name}`,
        );
        if (s > 0) {
          hits.set(tool.name, {
            piName: tool.name,
            serverName: server.name,
            description: truncateDescription(tool.description),
            connected: false,
            score: s,
          });
        }
      }
      continue;
    }
    // Never connected (no cache yet): surface the server itself so the
    // model can opt to connect + discover its real tool list.
    const desc =
      server.config.description ??
      `MCP server "${server.name}" — not yet connected, tools unknown`;
    const s = score(queryTerms, `${server.name} ${desc}`);
    if (s > 0) {
      hits.set(`__server__${server.name}`, {
        serverName: server.name,
        description: truncateDescription(desc),
        connected: false,
        score: s,
      });
    }
  }

  return [...hits.values()].sort((a, b) => b.score - a.score).slice(0, limit);
}

function formatHits(hits: Hit[]): string {
  if (hits.length === 0) {
    return "mcp: no matching tools or servers. Try different keywords.";
  }
  // `hit.description` is already truncated at construction time (see
  // `search()`), so both this model-facing text and the renderer
  // (render.ts's `formatHitLine`, which reads the same `Hit` objects via
  // `details.hits`) show the same bounded length — never a server's full,
  // possibly multi-page tool description.
  return hits
    .map((hit) => {
      if (!hit.piName) {
        return `${hit.serverName} (server, not connected) — ${hit.description} — call mcp({ tool: "${hit.serverName}" }) to connect`;
      }
      const suffix = hit.connected
        ? ""
        : " (not connected — connects on first call)";
      return `${hit.piName}${suffix} — ${hit.description}`;
    })
    .join("\n");
}

/**
 * Poll until a server currently `starting` settles (started elsewhere, e.g.
 * a racing call). Returns `false` if it's still `starting` when `timeoutMs`
 * elapses, so callers can distinguish "timed out" from "settled" instead of
 * re-deriving that from state + `lastError`, which is null while a server
 * simply hasn't finished starting yet.
 */
async function waitWhileStarting(
  manager: ServerManager,
  serverName: string,
  timeoutMs = 30_000,
): Promise<boolean> {
  const start = Date.now();
  while (manager.getServer(serverName)?.state === "starting") {
    if (Date.now() - start > timeoutMs) return false;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return true;
}

/** Ensure a server is connected, starting it on demand. Returns an error message, or `null` on success. */
async function ensureStarted(
  manager: ServerManager,
  deps: ProxyToolDeps,
  serverName: string,
): Promise<string | null> {
  const server = manager.getServer(serverName);
  if (!server) return `mcp: no server named "${serverName}"`;
  let timedOut = false;
  if (server.state === "stopped") {
    await manager.startServer(serverName, deps.getCwd());
  } else if (server.state === "starting") {
    timedOut = !(await waitWhileStarting(manager, serverName));
  }
  const after = manager.getServer(serverName);
  if (after?.state !== "ready") {
    const message = timedOut
      ? "timed out waiting for server to start"
      : (after?.lastError?.message ?? "unknown error");
    const hint = after?.config.auth ? deps.authHint(serverName, message) : "";
    return `mcp: failed to start "${serverName}" — ${message}${hint}`;
  }
  manager.touch(serverName);
  return null;
}

async function findCachedOwner(
  manager: ServerManager,
  toolCache: McpToolCache | null,
  piName: string,
): Promise<string | undefined> {
  if (!toolCache) return undefined;
  // Same reasoning as `search()` above: read the cache file once, not once
  // per non-ready server.
  const cachedAll = await toolCache.all();
  for (const server of manager.getAllServers()) {
    if (server.state === "ready") continue;
    const cached = cachedAll[server.name];
    if (cached?.tools.some((t) => t.name === piName)) return server.name;
  }
  return undefined;
}

function textContent(text: string, details: McpProxyDetails) {
  return {
    content: [{ type: "text" as const, text }] as BridgedContent[],
    details,
  };
}

/**
 * Cap a single tool's description length. Some MCP servers ship very long,
 * multi-paragraph descriptions (data-warehouse setup guides, workflow
 * docs, ...) — without this, a handful of search hits or one server's
 * discovery listing can blow past a reasonable context budget on their own.
 */
const MAX_DESCRIPTION_CHARS = 200;

function truncateDescription(description: string): string {
  return description.length > MAX_DESCRIPTION_CHARS
    ? `${description.slice(0, MAX_DESCRIPTION_CHARS)}…`
    : description;
}

async function callOrConnect(
  manager: ServerManager,
  bridge: ToolBridge,
  deps: ProxyToolDeps,
  name: string,
  argsJson: string | undefined,
  signal: AbortSignal | undefined,
): Promise<{ content: BridgedContent[]; details: McpProxyDetails }> {
  // Exact server name (not also a live tool name): connect only — never
  // dump the discovered catalog into context. A server can expose hundreds
  // of tools with long descriptions (real example: 651 tools, 520KB of
  // text), which would blow the context budget in one tool result. Point
  // the model at `search` instead, same as any other discovery.
  const server = manager.getServer(name);
  if (server && !bridge.hasTool(name)) {
    const error = await ensureStarted(manager, deps, name);
    if (error) return textContent(error, { kind: "error", message: error });
    const count = bridge
      .getSearchableTools()
      .filter((t) => t.serverName === name).length;
    return textContent(
      count > 0
        ? `mcp: connected to "${name}" (${count} tool${count === 1 ? "" : "s"} discovered). Call mcp({ search: "keywords" }) to find the ones you need — do not list them all.`
        : `mcp: connected to "${name}" (no tools reported).`,
      { kind: "connect", server: name, toolCount: count },
    );
  }

  let owner: string | undefined = bridge.hasTool(name)
    ? bridge.getToolMeta(name)?.serverName
    : undefined;
  if (!owner) owner = await findCachedOwner(manager, deps.getToolCache(), name);
  if (!owner) {
    const message = `mcp: no tool or server named "${name}". Call mcp({ search: "..." }) first.`;
    return textContent(message, { kind: "error", message });
  }

  const error = await ensureStarted(manager, deps, owner);
  if (error) return textContent(error, { kind: "error", message: error });

  if (!bridge.hasTool(name)) {
    const message = `mcp: "${name}" is no longer offered by "${owner}" after connecting — call mcp({ search: "..." }) again.`;
    return textContent(message, { kind: "error", message });
  }

  let args: Record<string, unknown> = {};
  if (argsJson !== undefined && argsJson.trim() !== "") {
    try {
      const parsed: unknown = JSON.parse(argsJson);
      if (
        typeof parsed !== "object" ||
        parsed === null ||
        Array.isArray(parsed)
      ) {
        const message = `mcp: "args" must be a JSON object string.`;
        return textContent(message, { kind: "error", message });
      }
      args = parsed as Record<string, unknown>;
    } catch (err) {
      const message = `mcp: "args" is not valid JSON — ${describeError(err)}`;
      return textContent(message, { kind: "error", message });
    }
  }

  const meta = bridge.getToolMeta(name);
  const client = manager.getServer(owner)?.client;
  if (!meta || !client) {
    const message = `mcp: "${name}" is unavailable right now — try again.`;
    return textContent(message, { kind: "error", message });
  }

  manager.touch(owner);
  const timeoutMs = manager.getRequestTimeoutMs(owner);
  const { content } = await invokeTool(
    client,
    owner,
    meta.mcpName,
    args,
    timeoutMs,
    signal,
  );
  return {
    content,
    details: { kind: "call", server: owner, tool: meta.mcpName, piName: name },
  };
}

export function createMcpProxyTool(deps: ProxyToolDeps) {
  return defineTool({
    name: "mcp",
    label: "MCP",
    description:
      'Search for and call tools from configured MCP servers, without loading every tool schema into context. Use { "search": "keywords" } to find relevant tools or servers — this works even for servers that are not connected yet. Use { "tool": "<name>", "args": "<json-object-string>" } to call one by its exact name (from search), or to connect a not-yet-started server by its config name and discover its tools. Servers start automatically on first use.',
    promptSnippet:
      "mcp({ search }) / mcp({ tool, args }) — MCP tool search + call",
    parameters: Type.Object({
      search: Type.Optional(
        Type.String({
          description: "Keywords to find relevant MCP tools or servers.",
        }),
      ),
      tool: Type.Optional(
        Type.String({
          description:
            "Exact tool name (as returned by search) to call, or a configured MCP server name to connect and list its tools.",
        }),
      ),
      args: Type.Optional(
        Type.String({
          description:
            'JSON-encoded object of arguments for the tool call, e.g. \'{"path":"/tmp"}\'.',
        }),
      ),
    }),
    async execute(_toolCallId, params, signal) {
      const manager = deps.getManager();
      const bridge = deps.getBridge();
      if (!manager || !bridge) {
        return textContent("mcp: no MCP servers configured.", {
          kind: "no-config",
        });
      }
      if (params.search) {
        const settings = deps.getSettings();
        const hits = await search(
          manager,
          bridge,
          deps.getToolCache(),
          settings?.searchResultLimit ?? 15,
          params.search,
        );
        return textContent(formatHits(hits), {
          kind: "search",
          query: params.search,
          hits,
        });
      }
      if (params.tool) {
        return callOrConnect(
          manager,
          bridge,
          deps,
          params.tool,
          params.args,
          signal,
        );
      }
      return textContent(
        'mcp: pass { "search": "..." } to find tools, or { "tool": "..." } to call/connect one.',
        { kind: "usage" },
      );
    },
    renderCall(args, theme, context) {
      return renderMcpProxyCall(args, theme, context.expanded);
    },
    renderResult(result, options, theme) {
      return renderMcpProxyResult(result, options, theme);
    },
  });
}
