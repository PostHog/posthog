import {
  channelDisplayLabel,
  PERSONAL_CHANNEL_LABEL,
} from "@posthog/core/canvas/channelName";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { formatRelativeAge } from "@posthog/shared";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";

function ownedItemName(item: TaskActivityItem): string {
  switch (item.commentTarget?.scope) {
    case "desktop_canvas":
      return "canvas";
    case "task_artifact":
      return "artifact";
    default:
      return "task";
  }
}

function activityAction(
  item: TaskActivityItem,
  currentUserEmail?: string | null,
): string {
  switch (item.activityKind) {
    case "awaiting_input":
      return "Agent is waiting for your reply";
    case "completed":
      return "Agent completed";
    case "message":
      if (!item.author) {
        return "Agent replied";
      }
      return item.author.email === currentUserEmail
        ? "You replied"
        : `${userDisplayName(item.author)} replied`;
    case "mention":
      return `${userDisplayName(item.author)} mentioned you`;
    case "thread_reply":
      return `${userDisplayName(item.author)} replied to a thread you participated in`;
    case "owned_item_comment":
      return `${userDisplayName(item.author)} commented on your ${ownedItemName(item)}`;
    default:
      return "You created";
  }
}

function activitySpace(channelName: string | null): string | null {
  if (!channelName) {
    return null;
  }
  const label = channelDisplayLabel(channelName);
  return label === PERSONAL_CHANNEL_LABEL ? "Personal" : label;
}

export function activityMetadata(
  item: TaskActivityItem,
  currentUserEmail?: string | null,
): string {
  return [
    formatRelativeAge(item.activityAt),
    activityAction(item, currentUserEmail),
    activitySpace(item.channelName),
  ]
    .filter((part): part is string => part !== null)
    .join(" · ");
}
