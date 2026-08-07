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
