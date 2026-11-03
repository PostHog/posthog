import type { TaskActivity } from "@posthog/shared/domain-types";

// Inbox zero: which chats need the user, and why. A chat leaves the inbox when the user replies to it, or dismisses it
// from the row, never because they looked at it; a glance is not an action.

export type InboxReason = "prompt" | "failed" | "reply";

export interface InboxChat {
  // The agent is mid-turn, or a message to it is on its way.
  working: boolean;
  // The agent asked something: a permission request or a question on the sheet.
  prompted: boolean;
  // The run failed, and no reply brings it back.
  failed: boolean;
  // The last turn ended and the agent waits on nothing of its own.
  turnEndedAt: number | null;
  shells: number;
  wake: boolean;
  // The user's last message (epoch ms), or null before the first.
  repliedAt: number | null;
  // Dismissed from the inbox at (epoch ms); a turn ending after that brings it back.
  dismissedAt: number | null;
  // Everything that ended before this (epoch ms) was marked read at once, with /inbox clear.
  readBefore: number | null;
}

// Why a chat sits in the inbox, or null when it does not.
export function inboxReason(chat: InboxChat): InboxReason | null {
  if (chat.prompted) return "prompt";
  if (chat.working) return null;
  if (chat.failed) return "failed";
  if (chat.turnEndedAt === null) return null;
  // A shell still running or a scheduled wake-up means the agent is not done with its own work.
  if (chat.shells > 0 || chat.wake) return null;
  if (chat.repliedAt !== null && chat.repliedAt >= chat.turnEndedAt)
    return null;
  if (chat.dismissedAt !== null && chat.dismissedAt >= chat.turnEndedAt)
    return null;
  if (chat.readBefore !== null && chat.readBefore >= chat.turnEndedAt)
    return null;
  return "reply";
}

// A cloud chat's inbox facts from the server's activity feed, which flips to a completed turn or a question the
// moment the server knows, so a chat is in the inbox before its log has been read here. The row's own read mark
// stands in for a dismissal, since a reply or a dismissal here marks it read on the server.
export function feedChat(
  row: TaskActivity,
  working: boolean,
  prompted: boolean,
  failed: boolean,
): Pick<InboxChat, "working" | "prompted" | "failed" | "turnEndedAt"> | null {
  if (
    row.activity_kind !== "completed" &&
    row.activity_kind !== "awaiting_input"
  )
    return null;
  const at = Date.parse(row.activity_at);
  return {
    working,
    prompted:
      prompted || (row.activity_kind === "awaiting_input" && row.is_unread),
    failed,
    turnEndedAt: row.is_unread && !Number.isNaN(at) ? at : null,
  };
}
