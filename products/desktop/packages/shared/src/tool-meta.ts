/**
 * Canonical, harness-neutral tool metadata carried on an ACP tool call's
 * `_meta.posthog`. Each adapter (the native-protocol → ACP boundary) populates
 * it, so the renderer never has to know which harness produced a tool call.
 *
 * The renderer reads through {@link readAgentToolName} / {@link readMcpToolName},
 * which prefer this channel and fall back to the legacy `_meta.claudeCode.toolName`
 * the Claude adapter still writes. New adapters should only populate `posthog`.
 */
export interface PosthogToolMeta {
  /** Agent-facing tool name, e.g. "Bash" or "mcp__posthog__exec". */
  toolName: string;
  /** Set only for MCP tool calls — the originating server + tool. */
  mcp?: { server: string; tool: string };
  /** Parent subagent tool call for nested activity. */
  parentToolCallId?: string;
}

/** `_meta` fragment for adapters to spread onto a tool_call update. */
export function posthogToolMeta(meta: PosthogToolMeta): {
  posthog: PosthogToolMeta;
} {
  return { posthog: meta };
}

/** Build the canonical `mcp__<server>__<tool>` key. */
export function mcpToolKey(mcp: { server: string; tool: string }): string {
  return `mcp__${mcp.server}__${mcp.tool}`;
}

/**
 * Parse a `mcp__<server>__<tool>` name into its parts; undefined when the name
 * isn't MCP-shaped. The server segment never contains `__`, so the first `__`
 * after the prefix terminates it and the remainder is the tool.
 */
export function parseMcpToolName(
  toolName: string,
): { server: string; tool: string } | undefined {
  const PREFIX = "mcp__";
  if (!toolName.startsWith(PREFIX)) return undefined;
  const rest = toolName.slice(PREFIX.length);
  const sep = rest.indexOf("__");
  if (sep <= 0 || sep + 2 >= rest.length) return undefined;
  return { server: rest.slice(0, sep), tool: rest.slice(sep + 2) };
}

interface ToolCallMeta {
  posthog?: PosthogToolMeta;
  /** Legacy Claude-adapter channel, read only as a fallback. */
  claudeCode?: { toolName?: string; parentToolCallId?: string };
}

function asToolCallMeta(meta: unknown): ToolCallMeta | undefined {
  return meta && typeof meta === "object" ? (meta as ToolCallMeta) : undefined;
}

/** Canonical agent-facing tool name: neutral channel first, legacy fallback. */
export function readAgentToolName(meta: unknown): string | undefined {
  const m = asToolCallMeta(meta);
  return m?.posthog?.toolName ?? m?.claudeCode?.toolName;
}

/** Parent subagent tool call: neutral channel first, legacy fallback. */
export function readParentToolCallId(meta: unknown): string | undefined {
  const m = asToolCallMeta(meta);
  const canonical = m?.posthog?.parentToolCallId;
  if (typeof canonical === "string" && canonical.length > 0) return canonical;
  const legacy = m?.claudeCode?.parentToolCallId;
  return typeof legacy === "string" && legacy.length > 0 ? legacy : undefined;
}

/**
 * The MCP `{ server, tool }` descriptor for a tool call, or undefined for a
 * non-MCP call. Prefers the structured channel, else parses the legacy
 * `mcp__…` name.
 */
export function readMcpToolDescriptor(
  meta: unknown,
): { server: string; tool: string } | undefined {
  const m = asToolCallMeta(meta);
  if (m?.posthog?.mcp) return m.posthog.mcp;
  const name = m?.posthog?.toolName ?? m?.claudeCode?.toolName;
  return name ? parseMcpToolName(name) : undefined;
}

/**
 * Canonical `mcp__server__tool` key for a tool call, or undefined for a non-MCP
 * call. Convenience for components still keyed on the string form.
 */
export function readMcpToolName(meta: unknown): string | undefined {
  const mcp = readMcpToolDescriptor(meta);
  return mcp ? mcpToolKey(mcp) : undefined;
}
