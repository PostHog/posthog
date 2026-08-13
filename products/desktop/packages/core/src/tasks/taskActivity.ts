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
 * When something last happened in the session, as an ISO string.
 *
 * `last_activity_at` is the backend's answer and the one to trust: it moves on a thread
 * message and on a run starting, streaming, or finishing. `updated_at` is the fallback for a
 * response that predates the field, and it only moves when the task row itself is written —
 * which is why a list ordered by it comes out in creation order.
 */
export function taskActivityAt(
  task: Pick<TaskActivityInput, "created_at" | "updated_at" | "last_activity_at">,
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
