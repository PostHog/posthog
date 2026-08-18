import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";

export function getUnreadActivityItems(
  items: TaskActivityItem[],
): TaskActivityItem[] {
  return items.filter((item) => item.isUnread);
}

export function getVisibleActivityItems(
  items: TaskActivityItem[],
  showMyActivity: boolean,
  currentUserId?: number,
): TaskActivityItem[] {
  if (showMyActivity) {
    return items;
  }
  return items.filter(
    (item) =>
      item.activityKind !== "created" &&
      (currentUserId === undefined || item.author?.id !== currentUserId),
  );
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
