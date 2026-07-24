import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { RenderItem } from "@posthog/ui/features/sessions/components/session-update/SessionUpdateView";

function extractRenderItemText(update: RenderItem): string {
  switch (update.sessionUpdate) {
    case "agent_message_chunk":
    case "agent_thought_chunk":
      return "content" in update && update.content.type === "text"
        ? update.content.text
        : "";
    case "tool_call":
      // Tool calls are excluded from search. Each tool type renders its
      // collapsed state differently so extracted text wouldn't match the
      // DOM, causing count mismatches with visible highlights.
      return "";
    case "console":
      return update.message;
    case "error":
      return update.message;
    case "status":
      return update.status;
    case "task_notification":
      return update.summary;
    default:
      return "";
  }
}

export function extractSearchableText(item: ConversationItem): string {
  switch (item.type) {
    case "user_message":
      return item.content;
    case "session_update":
      return extractRenderItemText(item.update);
    case "user_shell_execute":
      return [
        item.command,
        item.result?.stdout ?? "",
        item.result?.stderr ?? "",
      ].join(" ");
    case "turn_cancelled":
      return item.interruptReason ?? "Interrupted by user";
    case "git_action":
    case "skill_button_action":
    case "git_action_result":
      return "";
  }
}
