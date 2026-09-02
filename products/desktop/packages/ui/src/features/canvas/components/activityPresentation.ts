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
  spaceLabel: string | null;
}

interface ActivityEventPresentation {
  action: string;
  actionInSpace: string;
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
        actionInSpace: "Agent is waiting for your reply in",
        agentIcon: "question",
      };
    case "completed":
      return {
        action: "Agent finished",
        actionInSpace: "Agent finished in",
        agentIcon: "check",
      };
    case "message": {
      if (!item.author) {
        return {
          action: "Agent replied",
          actionInSpace: "Agent replied in",
          agentIcon: "chat",
        };
      }
      const replyAction =
        item.author.email === currentUserEmail
          ? "You replied"
          : `${userDisplayName(item.author)} replied`;
      return {
        action: replyAction,
        actionInSpace: `${replyAction} in`,
        agentIcon: null,
      };
    }
    case "mention":
      return {
        action: `${userDisplayName(item.author)} mentioned you`,
        actionInSpace: `${userDisplayName(item.author)} mentioned you in`,
        agentIcon: null,
      };
    case "thread_reply":
      return {
        action: `${userDisplayName(item.author)} replied to a thread you participated in`,
        actionInSpace: `${userDisplayName(item.author)} replied to a thread in`,
        agentIcon: null,
      };
    case "owned_item_comment":
      return {
        action: `${userDisplayName(item.author)} commented on your ${ownedItemName(item)}`,
        actionInSpace: `${userDisplayName(item.author)} commented on your ${ownedItemName(item)} in`,
        agentIcon: null,
      };
    case "created":
      return {
        action: "You created",
        actionInSpace: "You created task in:",
        agentIcon: null,
      };
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
  const spaceLabel = activitySpace(item.channelName);
  const action = spaceLabel ? event.actionInSpace : event.action;
  return {
    agentIcon: event.agentIcon,
    metadata: [formatRelativeAge(item.activityAt), action].join(" · "),
    spaceLabel,
  };
}
