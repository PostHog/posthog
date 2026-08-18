import { isContentlessTask } from "@posthog/shared/domain-types";

export type TaskActivitySortMode = "created" | "updated";

export interface TaskActivityInput {
  title: string;
  slug: string;
  description?: string | null;
  internal?: boolean;
  created_at: string;
  updated_at?: string | null;
  latest_run?: { updated_at: string };
}

/**
 * The newest timestamp a run carries, or 0 for a task that has never run.
 *
 * `completed_at` is in the max because runs written by older servers persisted the terminal time
 * without their own `updated_at`, so they finish with a `completed_at` that is later. `created_at`
 * is deliberately absent: `auto_now` sets `updated_at` on insert, so it can never exceed it.
 *
 * A structural parameter type because `/tasks/summaries/` returns a run with only `status` and
 * `environment` — a caller on that endpoint gets 0 here rather than a wrong claim.
 */
export function runActivityTimestamp(
  run:
    | { updated_at?: string | null; completed_at?: string | null }
    | null
    | undefined,
): number {
  if (!run) return 0;
  return Math.max(
    Date.parse(run.updated_at ?? "") || 0,
    Date.parse(run.completed_at ?? "") || 0,
  );
}

export function taskActivityTimestamp(
  task: Pick<TaskActivityInput, "created_at" | "updated_at" | "latest_run">,
  sortMode: TaskActivitySortMode,
): number {
  if (sortMode === "created") {
    return new Date(task.created_at).getTime();
  }

  const runUpdatedAt = task.latest_run?.updated_at;
  return Math.max(
    runUpdatedAt ? new Date(runUpdatedAt).getTime() : 0,
    new Date(task.updated_at ?? task.created_at).getTime(),
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
