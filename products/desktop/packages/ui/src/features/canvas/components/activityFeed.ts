import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { formatShortDayLabel, getLocalDayKey } from "@posthog/shared";

export interface ActivityDayGroup<T> {
  key: string;
  label: string;
  items: T[];
}

export function groupActivityItemsByDay<T extends { activityAt: string }>(
  items: readonly T[],
  now: Date = new Date(),
): ActivityDayGroup<T>[] {
  const groups = new Map<string, ActivityDayGroup<T>>();
  for (const item of items) {
    const timestamp = Math.min(new Date(item.activityAt).getTime(), +now);
    const key = `day:${getLocalDayKey(timestamp)}`;
    const group = groups.get(key);
    if (group) {
      group.items.push(item);
      continue;
    }
    groups.set(key, {
      key,
      label: formatShortDayLabel(timestamp, now),
      items: [item],
    });
  }
  return [...groups.values()];
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
