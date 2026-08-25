import { isContentlessTask } from "@posthog/shared/domain-types";

export type TaskActivitySortMode = "created" | "updated";

export interface TaskActivityInput {
  title: string;
  slug: string;
  description?: string | null;
  internal?: boolean;
  created_at: string;
  updated_at?: string | null;
  last_activity_at?: string | null;
  latest_run?: { updated_at: string };
}

/**
 * The session's activity time as an ISO string. Prefers `last_activity_at` (the backend's
 * answer, which moves on a thread message or a run starting, streaming, or finishing) and falls
 * back to `updated_at` only for responses that predate the field. Ordering by that fallback
 * comes out in creation order, because `updated_at` moves only when the row itself is written.
 */
export function taskActivityAt(
  task: Pick<
    TaskActivityInput,
    "created_at" | "updated_at" | "last_activity_at"
  >,
): string {
  return task.last_activity_at || task.updated_at || task.created_at;
}

export function taskActivityTimestamp(
  task: Pick<
    TaskActivityInput,
    "created_at" | "updated_at" | "last_activity_at" | "latest_run"
  >,
  sortMode: TaskActivitySortMode,
): number {
  if (sortMode === "created") {
    return new Date(task.created_at).getTime();
  }

  // The run's own timestamp still counts: it is the one activity signal a client talking to a
  // backend without `last_activity_at` can see move during a run.
  const runUpdatedAt = task.latest_run?.updated_at;
  return Math.max(
    runUpdatedAt ? new Date(runUpdatedAt).getTime() : 0,
    new Date(taskActivityAt(task)).getTime(),
  );
}

export function filterAndSortTasks<TaskType extends TaskActivityInput>(
  tasks: readonly TaskType[],
  sortMode: TaskActivitySortMode,
  showInternal: boolean,
  filter: string,
): TaskType[] {
  const normalizedFilter = filter.toLowerCase();

  return tasks
    .filter((task) => !isContentlessTask(task))
    .filter((task) =>
      showInternal ? task.internal === true : task.internal !== true,
    )
    .filter(
      (task) =>
        !normalizedFilter ||
        task.title.toLowerCase().includes(normalizedFilter) ||
        task.slug.toLowerCase().includes(normalizedFilter) ||
        task.description?.toLowerCase().includes(normalizedFilter),
    )
    .sort(
      (firstTask, secondTask) =>
        taskActivityTimestamp(secondTask, sortMode) -
        taskActivityTimestamp(firstTask, sortMode),
    );
}
