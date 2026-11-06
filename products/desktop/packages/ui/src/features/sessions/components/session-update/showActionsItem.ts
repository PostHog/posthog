import { isShowActionsCall } from "@posthog/core/sessions/showActions";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { ToolCall } from "@posthog/ui/features/sessions/types";

export function isShowActionsItem(
  item: ConversationItem,
  toolCalls?: Map<string, ToolCall>,
): boolean {
  if (
    item.type !== "session_update" ||
    item.update.sessionUpdate !== "tool_call"
  ) {
    return false;
  }
  const resolved = (toolCalls ?? item.turnContext.toolCalls).get(
    item.update.toolCallId,
  );
  return (
    isShowActionsCall(resolved?._meta) || isShowActionsCall(item.update._meta)
  );
}
