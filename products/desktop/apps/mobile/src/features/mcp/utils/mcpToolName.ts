// Helpers for detecting + parsing MCP tool names that arrive from the agent.
//
// Cloud agents prefix MCP tool calls with `mcp__<server>__<tool>` in the raw
// tool name (mobile sees this on `_meta.claudeCode.toolName`). PostHog's own
// MCP plugin already has its own dedicated renderer (`isPostHogExecTool`); we
// pick up everything else.

const MCP_PREFIX = "mcp__";

/** Returns true for any tool name following the MCP naming convention. */
export function isMcpToolName(toolName: string | undefined | null): boolean {
  if (!toolName) return false;
  if (!toolName.startsWith(MCP_PREFIX)) return false;
  const rest = toolName.slice(MCP_PREFIX.length);
  return rest.includes("__");
}

export interface ParsedMcpToolName {
  serverName: string;
  toolName: string;
}

/** Split `mcp__<server>__<tool>` into its parts, or `null` if it doesn't match. */
export function parseMcpToolName(
  raw: string | undefined | null,
): ParsedMcpToolName | null {
  if (!raw || !raw.startsWith(MCP_PREFIX)) return null;
  const rest = raw.slice(MCP_PREFIX.length);
  const splitIdx = rest.indexOf("__");
  if (splitIdx <= 0) return null;
  return {
    serverName: rest.slice(0, splitIdx),
    toolName: rest.slice(splitIdx + 2),
  };
}
