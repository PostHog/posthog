import {
  type TaskActivitySortMode,
  taskActivityTimestamp,
} from "@posthog/core/tasks/taskActivity";
import type { Task } from "@posthog/shared";
import type { OrganizeMode } from "../stores/taskStore";

export const NO_REPO_LABEL = "No repository";

export const ATTENTION_GROUP_KEY = "attention";
export const ATTENTION_GROUP_LABEL = "Needs attention";

export type TaskListItem =
  | { type: "task"; task: Task }
  | {
      type: "attention-header";
      groupKey: string;
      label: string;
      count: number;
      collapsed: boolean;
    }
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

/** Newest activity first — the one ordering every group in this list uses. */
function byActivityDesc(
  sortMode: TaskActivitySortMode,
): (a: Task, b: Task) => number {
  return (a, b) =>
    taskActivityTimestamp(b, sortMode) - taskActivityTimestamp(a, sortMode);
}

interface BuildTaskListItemsOptions {
  /** Already filtered to what the list should show (e.g. minus archived). */
  tasks: readonly Task[];
  organizeMode: OrganizeMode;
  sortMode: TaskActivitySortMode;
  collapsedGroupKeys: ReadonlySet<string>;
  /** Tasks blocked on the user, pinned into their own group above everything. */
  awaitingInputTaskIds?: ReadonlySet<string>;
  now?: number;
}

/**
 * Flattens tasks into the FlatList's header/task rows. A collapsed group keeps
 * its header (and its full count, so the header still says how much is hidden)
 * and drops its task rows.
 *
 * Tasks blocked on the user are lifted out of their normal group into a
 * "Needs attention" group at the top, in both organize modes — a task waiting on
 * a reply is the one thing worth acting on, and burying it under a repo or date
 * heading is what the grouping was hiding. They appear there and nowhere else,
 * so every row still has a unique key.
 */
export function buildTaskListItems({
  tasks,
  organizeMode,
  sortMode,
  collapsedGroupKeys,
  awaitingInputTaskIds,
  now = Date.now(),
}: BuildTaskListItemsOptions): TaskListItem[] {
  const items: TaskListItem[] = [];
  const byActivity = byActivityDesc(sortMode);

  const isAwaiting = (task: Task) =>
    awaitingInputTaskIds?.has(task.id) === true;
  const awaitingTasks = tasks.filter(isAwaiting);
  const restingTasks = tasks.filter((task) => !isAwaiting(task));

  if (awaitingTasks.length > 0) {
    const collapsed = collapsedGroupKeys.has(ATTENTION_GROUP_KEY);
    items.push({
      type: "attention-header",
      groupKey: ATTENTION_GROUP_KEY,
      label: ATTENTION_GROUP_LABEL,
      count: awaitingTasks.length,
      collapsed,
    });
    if (!collapsed) {
      awaitingTasks.sort(byActivity);
      for (const task of awaitingTasks) {
        items.push({ type: "task", task });
      }
    }
  }

  if (organizeMode === "by-project") {
    const groups = new Map<string, Task[]>();
    for (const task of restingTasks) {
      const key = task.repository?.trim() || NO_REPO_LABEL;
      const bucket = groups.get(key);
      if (bucket) {
        bucket.push(task);
      } else {
        groups.set(key, [task]);
      }
    }

    for (const tasksInRepo of groups.values()) {
      tasksInRepo.sort(byActivity);
    }

    const groupEntries = Array.from(groups.entries()).sort((a, b) => {
      if (a[0] === NO_REPO_LABEL) return 1;
      if (b[0] === NO_REPO_LABEL) return -1;
      return byActivity(a[1][0], b[1][0]);
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

  const sorted = [...restingTasks].sort(byActivity);

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
