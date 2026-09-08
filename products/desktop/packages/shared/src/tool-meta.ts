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
  mcpInstallationId?: string;
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

const CALL_TOOL_RESULT_OPTIONAL_KEYS = [
  "structuredContent",
  "isError",
  "_meta",
] as const;

/**
 * Some sources (the Codex app-server) serialize absent optional
 * `CallToolResult` fields as JSON `null`. The app-side zod schema types them
 * `.optional()`, not nullable, so an explicit null fails validation and drops
 * the whole tool result, leaving the app on its loading state. Call this
 * before a raw MCP result reaches an MCP App.
 */
export function omitNullCallToolResultFields<T>(result: T): T {
  if (result == null || typeof result !== "object") return result;
  const record = result as Record<string, unknown>;
  if (!CALL_TOOL_RESULT_OPTIONAL_KEYS.some((key) => record[key] === null)) {
    return result;
  }
  const stripped: Record<string, unknown> = { ...record };
  for (const key of CALL_TOOL_RESULT_OPTIONAL_KEYS) {
    if (stripped[key] === null) delete stripped[key];
  }
  return stripped as T;
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

export function readMcpInstallationId(meta: unknown): string | undefined {
  return asToolCallMeta(meta)?.posthog?.mcpInstallationId;
}
