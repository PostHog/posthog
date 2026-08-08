import type { TaskRun } from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useCallback } from "react";

const TASK_RUNS_POLL_INTERVAL_MS = 30_000;

/**
 * Every run of a task — for gathering artifacts across all runs, not just the
 * latest. The server never pushes manifest changes, so `refreshKey` lets
 * callers force a fresh fetch the moment they see one land (for example a
 * completed `upload_artifact` tool call) instead of waiting out the poll.
 */
export function useTaskRuns(
  taskId: string | undefined,
  refreshKey = 0,
): {
  runs: TaskRun[];
  isLoading: boolean;
  refreshRuns: () => Promise<TaskRun[]>;
} {
  const query = useAuthenticatedQuery<TaskRun[]>(
    ["task-runs", taskId ?? "none", refreshKey],
    (client) => client.listTaskRuns(taskId as string),
    {
      enabled: !!taskId,
      refetchInterval: TASK_RUNS_POLL_INTERVAL_MS,
    },
  );
  const refreshRuns = useCallback(async (): Promise<TaskRun[]> => {
    const result = await query.refetch();
    if (result.error) throw result.error;
    return result.data ?? [];
  }, [query.refetch]);
  return { runs: query.data ?? [], isLoading: query.isLoading, refreshRuns };
}
