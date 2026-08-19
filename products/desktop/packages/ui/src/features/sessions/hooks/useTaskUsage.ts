import type { TaskUsage } from "@posthog/api-client/posthog-client";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useQuery } from "@tanstack/react-query";

const TASK_USAGE_REFRESH_MS = 60_000;

export function useTaskUsage(taskId: string | undefined, enabled: boolean) {
  const client = useOptionalAuthenticatedClient();
  return useQuery({
    queryKey: ["task-usage", taskId],
    queryFn: (): Promise<TaskUsage> => {
      if (!client || !taskId) throw new Error("Task usage is unavailable");
      return client.getTaskUsage(taskId);
    },
    enabled: enabled && client !== null && taskId !== undefined,
    staleTime: TASK_USAGE_REFRESH_MS,
    refetchInterval: TASK_USAGE_REFRESH_MS,
    refetchOnMount: "always",
  });
}
