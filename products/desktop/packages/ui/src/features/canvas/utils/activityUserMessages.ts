import type { UserMessageLike } from "@posthog/core/canvas/activityTimeline";
import type { buildConversationItems } from "@posthog/ui/features/sessions/components/buildConversationItems";

type ConversationItem = ReturnType<
  typeof buildConversationItems
>["items"][number];

/**
 * The prompts a person sent, as activity-timeline rows. Shared by the drawn
 * timeline and the canvas snapshot, so the two surfaces order a task's prompts
 * the same way.
 *
 * A prompt pinned to the top of the transcript is the one that opened the task,
 * so it takes the task's own time instead of the time the transcript received
 * it.
 */
export function toActivityUserMessages(
  conversationItems: readonly ConversationItem[],
  taskCreatedAt: string,
): UserMessageLike[] {
  const taskCreatedTimestamp = Date.parse(taskCreatedAt);
  return conversationItems.reduce<UserMessageLike[]>((items, item) => {
    if (item.type === "user_message") {
      items.push({
        id: item.id,
        content: item.content,
        timestamp:
          item.pinToTop === true && Number.isFinite(taskCreatedTimestamp)
            ? taskCreatedTimestamp
            : item.timestamp,
      });
    }
    return items;
  }, []);
}
