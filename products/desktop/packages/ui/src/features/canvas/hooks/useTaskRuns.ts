import type { TaskRun } from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

const TASK_RUNS_POLL_INTERVAL_MS = 30_000;

/** Every run of a task — for gathering artifacts across all runs, not just the latest. */
export function useTaskRuns(taskId: string | undefined): {
  runs: TaskRun[];
  isLoading: boolean;
} {
  const query = useAuthenticatedQuery<TaskRun[]>(
    ["task-runs", taskId ?? "none"],
    (client) => client.listTaskRuns(taskId as string),
    {
      enabled: !!taskId,
      refetchInterval: TASK_RUNS_POLL_INTERVAL_MS,
    },
  );
  return { runs: query.data ?? [], isLoading: query.isLoading };
}
