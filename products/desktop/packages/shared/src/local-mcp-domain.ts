// Host-agnostic shapes for the user's locally configured MCP servers
// (~/.claude.json) as they relate to cloud task runs. The workspace-server
// reads the config from disk; @posthog/core classifies each server by whether
// it can be imported into a cloud sandbox.

/** Where a local MCP server definition came from in ~/.claude.json. */
export type LocalMcpServerScope = "user" | "project";

/**
 * Normalized transport of a locally configured MCP server. `unknown` covers
 * entries whose shape we don't recognize (e.g. future config formats); they
 * are surfaced but never imported.
 */
export type LocalMcpTransport =
  | { type: "http" | "sse"; url: string; headers?: Record<string, string> }
  | { type: "stdio"; command: string; args?: string[] }
  | { type: "unknown" };

/**
 * A locally configured MCP server as reported by the workspace-server.
 * Deliberately excludes stdio `env` values, which routinely hold secrets the
 * renderer has no use for.
 */
export interface LocalMcpServerDescriptor {
  name: string;
  scope: LocalMcpServerScope;
  transport: LocalMcpTransport;
}

/**
 * A local MCP server in the shape the cloud sandbox accepts (mirrors the
 * agent server's `remoteMcpServerSchema`: `--mcpServers` / ACP `McpServer`).
 * Included in the task-run creation payload for servers classified as
 * importable.
 */
export interface McpServerConnection {
  type: "http" | "sse";
  name: string;
  url: string;
  headers: Array<{ name: string; value: string }>;
  /**
   * One line on what the server does. pi's `mcp` tool matches this when the model
   * searches for tools, which is the only way a server that has never been connected
   * can be found — its tool list isn't known yet. Strip it before handing servers to
   * claude or codex: those go over ACP, whose McpServer schema doesn't declare it.
   */
  description?: string;
}

/** The subset of a server config the ACP `McpServer` schema declares. */
export type AcpMcpServer = Omit<McpServerConnection, "description">;

/** Drop the pi-only fields, leaving the shape claude and codex accept over ACP. */
export function toAcpMcpServers(
  servers: McpServerConnection[],
): AcpMcpServer[] {
  return servers.map(({ description: _description, ...server }) => server);
}

/**
 * A desktop-only local MCP server designated for relaying into a cloud run
 * (docs/CLOUD-MCP-RELAY.md). Names only — the sandbox never learns the
 * server's command, env, URL, or headers; the desktop resolves the name
 * against local config at execution time.
 */
export interface CloudMcpServerRelayDesignation {
  name: string;
}
