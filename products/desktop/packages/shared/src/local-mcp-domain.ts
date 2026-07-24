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
export interface CloudMcpServerImport {
  type: "http" | "sse";
  name: string;
  url: string;
  headers: Array<{ name: string; value: string }>;
}

/**
 * A desktop-only local MCP server designated for relaying into a cloud run
 * (docs/cloud-mcp-relay.md). Names only — the sandbox never learns the
 * server's command, env, URL, or headers; the desktop resolves the name
 * against local config at execution time.
 */
export interface CloudMcpServerRelayDesignation {
  name: string;
}
