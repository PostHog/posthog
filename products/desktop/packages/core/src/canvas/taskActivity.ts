import type {
  TaskActivity,
  TaskActivityKind,
  UserBasic,
} from "@posthog/shared/domain-types";

/**
 * The Activity feed — tasks the current user is involved in (created, mentioned
 * in, or messaged in) — as served by the backend task-activity index
 * (`getTaskActivity`). One row per task, newest activity first; the client only
 * maps DTOs to items.
 */

export interface TaskActivityItem {
  id: string;
  taskId: string;
  taskTitle: string;
  /** Backend channel (tasks product Channel UUID); null for channel-less tasks. */
  channelId: string | null;
  /** Backend channel name, for the "#channel" label. */
  channelName: string | null;
  activityAt: string;
  activityKind: TaskActivityKind;
  /** Content of the message tied to the latest activity; empty for created rows. */
  snippet: string;
  author: UserBasic | null;
  messageId: string | null;
  isUnread: boolean;
}

/** Map activity DTOs (already newest-first from the backend) to feed items. */
export function toTaskActivityItems(
  activity: readonly TaskActivity[],
): TaskActivityItem[] {
  return activity.map((row) => ({
    id: row.id,
    taskId: row.task_id,
    taskTitle: row.task_title || "Untitled task",
    channelId: row.channel_id ?? null,
    channelName: row.channel_name ?? null,
    activityAt: row.activity_at,
    activityKind: row.activity_kind,
    snippet: row.snippet,
    author: row.latest_author ?? null,
    messageId: row.latest_message_id ?? null,
    isUnread: row.is_unread,
  }));
}
