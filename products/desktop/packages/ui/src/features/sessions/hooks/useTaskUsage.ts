import type { TaskUsage } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import type { UseQueryResult } from "@tanstack/react-query";

const TASK_USAGE_REFRESH_MS = 60_000;

export function useTaskUsage(
  taskId: string | undefined,
  enabled: boolean,
): UseQueryResult<TaskUsage> {
  return useAuthenticatedQuery(
    ["task-usage", taskId],
    (client): Promise<TaskUsage> => {
      if (!taskId) throw new Error("Task usage is unavailable");
      return client.getTaskUsage(taskId);
    },
    {
      enabled: enabled && taskId !== undefined,
      staleTime: TASK_USAGE_REFRESH_MS,
      refetchInterval: TASK_USAGE_REFRESH_MS,
      refetchOnMount: "always",
    },
  );
}
