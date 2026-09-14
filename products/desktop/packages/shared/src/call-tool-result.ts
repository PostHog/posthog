/**
 * Normalization for raw MCP `CallToolResult` payloads on their way to an
 * MCP App. Kept separate from `_meta` handling (see `tool-meta.ts`): a tool
 * result is the payload of a call, not tool metadata.
 */

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
