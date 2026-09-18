/**
 * Projects an MCP `CallToolResult` to the fields a model may see. MCP defines
 * result `_meta` as host-only, and PostHog carries an app's data payload there
 * (`com.posthog.mcp/app_data`) when `structuredContent` is suppressed from the
 * model, so any path that rebuilds a result into model input has to drop it.
 */
export function stripMcpResultMeta(value: unknown): unknown {
  if (
    value !== null &&
    typeof value === "object" &&
    "_meta" in value &&
    ("content" in value || "structuredContent" in value)
  ) {
    // ACP keeps app data for widgets, but a rebuilt transcript becomes model input.
    // Strip metadata before capping so UI data cannot consume the resume budget either.
    const { _meta, ...modelResult } = value;
    return modelResult;
  }
  return value;
}
