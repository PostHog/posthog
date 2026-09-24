import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

export interface FailedFollowupMessage {
  id: string;
  content: string;
  ts: string;
  truncated: boolean;
  resendable: boolean;
}

export function useFailedFollowupMessages(
  taskId: string | undefined,
  runId: string | undefined,
  enabled: boolean,
): FailedFollowupMessage[] {
  const { data } = useAuthenticatedQuery(
    ["failed-followup-messages", taskId, runId],
    (client) => {
      if (!taskId || !runId) throw new Error("Task run is unavailable");
      return client.getFailedTaskRunMessages(taskId, runId);
    },
    {
      enabled: enabled && !!taskId && !!runId,
      retry: false,
      refetchInterval: 10_000,
      refetchOnMount: "always",
    },
  );
  return data?.messages ?? [];
}
