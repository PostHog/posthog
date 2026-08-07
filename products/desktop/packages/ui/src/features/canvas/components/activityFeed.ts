import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";

export function getUnreadActivityItems(
  items: TaskActivityItem[],
): TaskActivityItem[] {
  return items.filter((item) => item.isUnread);
}

export function getVisibleActivityItems(
  items: TaskActivityItem[],
  commentsEnabled: boolean,
): TaskActivityItem[] {
  return commentsEnabled ? items : items.filter((item) => !item.commentId);
}

export function activityReadPayload(items: TaskActivityItem[]) {
  return items.map((item) => ({
    task_id: item.taskId,
    seen_before: item.activityAt,
    ...(item.commentId ? { activity_id: item.id } : {}),
  }));
}

export function markLoadedReadLabel(
  loadedUnreadCount: number,
  unreadCount: number,
): string {
  return loadedUnreadCount === unreadCount
    ? "Mark all as read"
    : "Mark visible as read";
}

export function activityUnreadTotalForLabel({
  commentsEnabled,
  unreadCount,
  loadedVisibleUnread,
  hasNextPage,
}: {
  commentsEnabled: boolean;
  unreadCount: number;
  loadedVisibleUnread: number;
  hasNextPage: boolean;
}): number {
  if (commentsEnabled) return unreadCount;
  return loadedVisibleUnread + (hasNextPage ? 1 : 0);
}
