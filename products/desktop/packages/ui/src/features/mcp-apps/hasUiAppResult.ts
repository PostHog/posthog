import { resolveResultResourceUri } from "@posthog/core/mcp-apps/schemas";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";

/**
 * Whether the item's resolved tool result carries a UI-app resource (an MCP
 * chart or inline app). Checked on the result, not the tool name: Codex routes
 * every tool through one inline-exec wrapper, so a name check would match
 * every call in the session, not just the one that renders a chart.
 */
export function hasUiAppResult(item: ConversationItem): boolean {
  if (item.type !== "session_update") return false;
  if (item.update.sessionUpdate !== "tool_call") return false;
  const { toolCallId } = item.update;
  const resolved = toolCallId
    ? item.turnContext.toolCalls.get(toolCallId)
    : undefined;
  return resolveResultResourceUri(resolved?.rawOutput) !== undefined;
}
