import {
  channelDisplayLabel,
  PERSONAL_CHANNEL_LABEL,
} from "@posthog/core/canvas/channelName";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { formatRelativeAge } from "@posthog/shared";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";

export type AgentActivityIconKind = "chat" | "check" | "question";

export interface ActivityPresentation {
  agentIcon: AgentActivityIconKind | null;
  metadata: string;
}

interface ActivityEventPresentation {
  action: string;
  agentIcon: AgentActivityIconKind | null;
}

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

function activityEventPresentation(
  item: TaskActivityItem,
  currentUserEmail?: string | null,
): ActivityEventPresentation {
  switch (item.activityKind) {
    case "awaiting_input":
      return {
        action: "Agent is waiting for your reply",
        agentIcon: "question",
      };
    case "completed":
      return { action: "Agent completed", agentIcon: "check" };
    case "message":
      if (!item.author) {
        return { action: "Agent replied", agentIcon: "chat" };
      }
      return {
        action:
          item.author.email === currentUserEmail
            ? "You replied"
            : `${userDisplayName(item.author)} replied`,
        agentIcon: null,
      };
    case "mention":
      return {
        action: `${userDisplayName(item.author)} mentioned you`,
        agentIcon: null,
      };
    case "thread_reply":
      return {
        action: `${userDisplayName(item.author)} replied to a thread you participated in`,
        agentIcon: null,
      };
    case "owned_item_comment":
      return {
        action: `${userDisplayName(item.author)} commented on your ${ownedItemName(item)}`,
        agentIcon: null,
      };
    case "created":
      return { action: "You created", agentIcon: null };
    default: {
      const exhaustiveActivityKind: never = item.activityKind;
      return exhaustiveActivityKind;
    }
  }
}

function activitySpace(channelName: string | null): string | null {
  if (!channelName) {
    return null;
  }
  const label = channelDisplayLabel(channelName);
  return label === PERSONAL_CHANNEL_LABEL ? "Personal" : label;
}

export function activityPresentation(
  item: TaskActivityItem,
  currentUserEmail?: string | null,
): ActivityPresentation {
  const event = activityEventPresentation(item, currentUserEmail);
  return {
    agentIcon: event.agentIcon,
    metadata: [
      formatRelativeAge(item.activityAt),
      event.action,
      activitySpace(item.channelName),
    ]
      .filter((part): part is string => part !== null)
      .join(" · "),
  };
}
