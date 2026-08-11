import {
  type TaskActivitySortMode,
  taskActivityTimestamp,
} from "@posthog/core/tasks/taskActivity";
import type { Task } from "@posthog/shared";
import type { OrganizeMode } from "../stores/taskStore";

export const NO_REPO_LABEL = "No repository";

export type TaskListItem =
  | { type: "task"; task: Task }
  | {
      type: "repo-header";
      groupKey: string;
      repoLabel: string;
      count: number;
      collapsed: boolean;
    }
  | {
      type: "date-header";
      groupKey: string;
      label: string;
      count: number;
      collapsed: boolean;
    };

// Namespaced so a repo literally called "Today" can't share collapse state
// with the chronological "Today" bucket.
export function repoGroupKey(repoLabel: string): string {
  return `repo:${repoLabel}`;
}

export function dateGroupKey(label: string): string {
  return `date:${label}`;
}

const DATE_GROUP_ORDER = [
  "Today",
  "Yesterday",
  "This week",
  "This month",
  "Earlier",
];

export function relativeDateGroup(ms: number, now: number): string {
  const startOfToday = new Date(now);
  startOfToday.setHours(0, 0, 0, 0);
  const startOfDate = new Date(ms);
  startOfDate.setHours(0, 0, 0, 0);
  const days = Math.round(
    (startOfToday.getTime() - startOfDate.getTime()) / 86_400_000,
  );
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "This week";
  if (days < 30) return "This month";
  return "Earlier";
}

interface BuildTaskListItemsOptions {
  /** Already filtered to what the list should show (e.g. minus archived). */
  tasks: readonly Task[];
  organizeMode: OrganizeMode;
  sortMode: TaskActivitySortMode;
  collapsedGroupKeys: ReadonlySet<string>;
  now?: number;
}

/**
 * Flattens tasks into the FlatList's header/task rows. A collapsed group keeps
 * its header (and its full count, so the header still says how much is hidden)
 * and drops its task rows.
 */
export function buildTaskListItems({
  tasks,
  organizeMode,
  sortMode,
  collapsedGroupKeys,
  now = Date.now(),
}: BuildTaskListItemsOptions): TaskListItem[] {
  const items: TaskListItem[] = [];

  if (organizeMode === "by-project") {
    const groups = new Map<string, Task[]>();
    for (const task of tasks) {
      const key = task.repository?.trim() || NO_REPO_LABEL;
      const bucket = groups.get(key);
      if (bucket) {
        bucket.push(task);
      } else {
        groups.set(key, [task]);
      }
    }

    for (const tasksInRepo of groups.values()) {
      tasksInRepo.sort(
        (a, b) =>
          taskActivityTimestamp(b, sortMode) -
          taskActivityTimestamp(a, sortMode),
      );
    }

    const groupEntries = Array.from(groups.entries()).sort((a, b) => {
      if (a[0] === NO_REPO_LABEL) return 1;
      if (b[0] === NO_REPO_LABEL) return -1;
      return (
        taskActivityTimestamp(b[1][0], sortMode) -
        taskActivityTimestamp(a[1][0], sortMode)
      );
    });

    for (const [repoLabel, tasksInRepo] of groupEntries) {
      const groupKey = repoGroupKey(repoLabel);
      const collapsed = collapsedGroupKeys.has(groupKey);
      items.push({
        type: "repo-header",
        groupKey,
        repoLabel,
        count: tasksInRepo.length,
        collapsed,
      });
      if (collapsed) continue;
      for (const task of tasksInRepo) {
        items.push({ type: "task", task });
      }
    }

    return items;
  }

  const sorted = [...tasks].sort(
    (a, b) =>
      taskActivityTimestamp(b, sortMode) - taskActivityTimestamp(a, sortMode),
  );

  const buckets = new Map<string, Task[]>();
  for (const task of sorted) {
    const label = relativeDateGroup(taskActivityTimestamp(task, sortMode), now);
    const bucket = buckets.get(label);
    if (bucket) {
      bucket.push(task);
    } else {
      buckets.set(label, [task]);
    }
  }

  for (const label of DATE_GROUP_ORDER) {
    const bucket = buckets.get(label);
    if (!bucket || bucket.length === 0) continue;
    const groupKey = dateGroupKey(label);
    const collapsed = collapsedGroupKeys.has(groupKey);
    items.push({
      type: "date-header",
      groupKey,
      label,
      count: bucket.length,
      collapsed,
    });
    if (collapsed) continue;
    for (const task of bucket) {
      items.push({ type: "task", task });
    }
  }

  return items;
}
