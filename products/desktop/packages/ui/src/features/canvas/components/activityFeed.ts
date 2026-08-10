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

/**
 * The unread total to show the viewer. The server counts comment activity whether
 * or not the comments flag is on, so with it off that total runs ahead of the rows
 * the feed renders; the loaded rows the viewer can see are the honest number there.
 */
export function visibleActivityUnreadCount({
  commentsEnabled,
  unreadCount,
  loadedVisibleUnread,
}: {
  commentsEnabled: boolean;
  unreadCount: number;
  loadedVisibleUnread: number;
}): number {
  return commentsEnabled ? unreadCount : loadedVisibleUnread;
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
  const visibleUnread = visibleActivityUnreadCount({
    commentsEnabled,
    unreadCount,
    loadedVisibleUnread,
  });
  if (commentsEnabled) return visibleUnread;
  // Counting only loaded rows cannot see unread activity on a further page, so
  // assume one is waiting and keep the action labelled as a partial read.
  return visibleUnread + (hasNextPage ? 1 : 0);
}
