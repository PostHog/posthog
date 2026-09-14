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

/** Largest serialized MCP tool result a host persists (transcript, rawOutput, cloud events). */
export const MAX_PERSISTED_MCP_RESULT_BYTES = 1_000_000;

const TRUNCATED_RESULT_MARKER =
  "[MCP tool result dropped: it was too large to store. " +
  "Narrow the query or arguments to get the full result.]";

function serializedLength(value: unknown): number {
  try {
    return JSON.stringify(value)?.length ?? 0;
  } catch {
    // Unserializable values cannot be persisted either; treat as oversized.
    return Number.POSITIVE_INFINITY;
  }
}

/** The `_meta` keys that route a result to its UI app; dropped when even these are too large. */
function uiRoutingMeta(
  meta: unknown,
  maxBytes: number,
): Record<string, unknown> | undefined {
  if (meta == null || typeof meta !== "object") return undefined;
  const record = meta as Record<string, unknown>;
  const routing: Record<string, unknown> = {};
  if (record.ui !== undefined) routing.ui = record.ui;
  if (record["ui/resourceUri"] !== undefined) {
    routing["ui/resourceUri"] = record["ui/resourceUri"];
  }
  if (Object.keys(routing).length === 0) return undefined;
  return serializedLength(routing) <= maxBytes ? routing : undefined;
}

/**
 * Bound a server-controlled MCP tool result before a host persists it: an
 * oversized payload must not grow the transcript and cloud storage without
 * limit. A result within the limit passes through unchanged; an oversized
 * one becomes a truncation marker plus the `_meta` routing keys, so a UI
 * app still renders.
 */
export function boundPersistedMcpResult<T extends object>(
  result: T,
  maxBytes: number = MAX_PERSISTED_MCP_RESULT_BYTES,
): T {
  const stripped = omitNullCallToolResultFields(result);
  if (serializedLength(stripped) <= maxBytes) return stripped;

  const bounded: Record<string, unknown> = {
    content: [{ type: "text", text: TRUNCATED_RESULT_MARKER }],
  };
  const routing = uiRoutingMeta(
    (stripped as Record<string, unknown>)._meta,
    maxBytes,
  );
  if (routing) bounded._meta = routing;
  if (typeof (stripped as Record<string, unknown>).isError === "boolean") {
    bounded.isError = (stripped as Record<string, unknown>).isError;
  }
  return bounded as T;
}
