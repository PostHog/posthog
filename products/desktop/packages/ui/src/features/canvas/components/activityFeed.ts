import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { formatShortDayLabel, getLocalDayKey } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";

export type ActivityFeedItem =
  | {
      kind: "task";
      id: string;
      activityAt: string;
      task: TaskActivityItem;
    }
  | {
      kind: "report";
      id: string;
      activityAt: string;
      report: SignalReport;
    };

export interface ActivityDayGroup<T> {
  key: string;
  label: string;
  items: T[];
}

export interface ActivityFeedContent {
  unreadItems: TaskActivityItem[];
  feedItems: ActivityFeedItem[];
  lastShownReportId: string | null;
  remainingInboxReportCount: number;
  selfDrivingIncluded: boolean;
}

export function deriveActivityFeedContent({
  taskItems,
  reports,
  totalReportCount,
  mentionsIncluded,
  reportsIncluded,
  unreadsOnly,
}: {
  taskItems: TaskActivityItem[];
  reports: SignalReport[];
  totalReportCount: number;
  mentionsIncluded: boolean;
  reportsIncluded: boolean;
  unreadsOnly: boolean;
}): ActivityFeedContent {
  const unreadItems = getUnreadActivityItems(taskItems);
  const visibleReports = unreadsOnly ? [] : reports;

  return {
    unreadItems,
    feedItems: mergeActivityFeedItems(
      mentionsIncluded ? (unreadsOnly ? unreadItems : taskItems) : [],
      visibleReports,
    ),
    lastShownReportId: visibleReports.at(-1)?.id ?? null,
    remainingInboxReportCount: Math.max(
      0,
      (unreadsOnly ? 0 : totalReportCount) - visibleReports.length,
    ),
    selfDrivingIncluded: !unreadsOnly && reportsIncluded,
  };
}

export function activityFeedSourceDescription(
  mentionsIncluded: boolean,
  selfDrivingIncluded: boolean,
): string {
  if (mentionsIncluded && selfDrivingIncluded) {
    return "Task updates and Self-driving reports appear here.";
  }
  if (mentionsIncluded) return "Task updates appear here.";
  if (selfDrivingIncluded) return "Self-driving reports appear here.";
  return "Choose what to include from the Activity actions menu.";
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

export function mergeActivityFeedItems(
  tasks: readonly TaskActivityItem[],
  reports: readonly SignalReport[],
): ActivityFeedItem[] {
  return [
    ...tasks.map(
      (task): ActivityFeedItem => ({
        kind: "task",
        id: `task:${task.id}`,
        activityAt: task.activityAt,
        task,
      }),
    ),
    ...reports.map(
      (report): ActivityFeedItem => ({
        kind: "report",
        id: `report:${report.id}`,
        activityAt: report.updated_at,
        report,
      }),
    ),
  ].sort(
    (left, right) =>
      new Date(right.activityAt).getTime() -
      new Date(left.activityAt).getTime(),
  );
}

export function filterActivityFeedItems(
  items: readonly ActivityFeedItem[],
  query: string,
): ActivityFeedItem[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return [...items];

  return items.filter((item) => {
    const searchableText =
      item.kind === "task"
        ? [
            item.task.taskTitle,
            item.task.channelName,
            item.task.snippet,
            item.task.author?.first_name,
            item.task.author?.last_name,
            item.task.author?.email,
          ]
        : [
            item.report.title,
            item.report.summary,
            item.report.priority,
            "Self-driving",
          ];

    return searchableText.some((value) =>
      value?.toLowerCase().includes(normalizedQuery),
    );
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
