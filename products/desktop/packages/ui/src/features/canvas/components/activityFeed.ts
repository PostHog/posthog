import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";

export type ActivityFeedView = "all" | "you" | "agent" | "others";

function isAgentActivity(item: TaskActivityItem): boolean {
  return (
    item.activityKind === "awaiting_input" ||
    item.activityKind === "completed" ||
    (item.activityKind === "message" && !item.author)
  );
}

export function getActivityItemsForView(
  items: TaskActivityItem[],
  view: ActivityFeedView,
  currentUserEmail?: string | null,
): TaskActivityItem[] {
  if (view === "all") return items;

  return items.filter((item) => {
    const agentActivity = isAgentActivity(item);
    const currentUserActivity =
      item.activityKind === "created" ||
      (!!currentUserEmail && item.author?.email === currentUserEmail);

    if (view === "agent") return agentActivity;
    if (view === "you") return currentUserActivity;
    return !agentActivity && !currentUserActivity;
  });
}

export function getUnreadActivityItems(
  items: TaskActivityItem[],
): TaskActivityItem[] {
  return items.filter((item) => item.isUnread);
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
