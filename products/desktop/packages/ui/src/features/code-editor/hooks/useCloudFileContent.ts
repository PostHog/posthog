import {
  CLOUD_TASK_CLIENT,
  type CloudTaskClient,
} from "@posthog/core/cloud-task/cloudTaskClient";
import {
  type CloudFileContent,
  extractCloudFileContent,
} from "@posthog/core/task-detail/cloudToolChanges";
import { useService } from "@posthog/di/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useSessionSelector } from "../../sessions/useSession";
import { useCloudEventSummary } from "../../task-detail/hooks/useCloudEventSummary";

export type CloudFileResult = CloudFileContent & { isLoading: boolean };

export function useCloudFileContent(
  taskId: string,
  filePath: string,
  enabled: boolean,
): CloudFileResult {
  const cloudTaskClient = useService<CloudTaskClient>(CLOUD_TASK_CLIENT);
  const runId = useSessionSelector(taskId, (value) => value?.taskRunId ?? null);
  const sessionStatus = useSessionSelector(
    taskId,
    (value) => value?.status ?? null,
  );
  const liveFile = useQuery({
    queryKey: ["cloud-file", taskId, runId, filePath],
    queryFn: async () => {
      const context = await cloudTaskClient.getContext();
      if (!context || !runId) {
        throw new Error("Cloud task context is unavailable");
      }
      const response = await cloudTaskClient.sendCommand({
        taskId,
        runId,
        apiHost: context.apiHost,
        teamId: context.teamId,
        method: "read_file",
        params: { filePath },
      });
      const result = response.result as { content?: unknown } | undefined;
      if (!response.success || typeof result?.content !== "string") {
        throw new Error(response.error ?? "File content is unavailable");
      }
      return result.content;
    },
    enabled: enabled && sessionStatus === "connected" && !!runId,
    retry: false,
    staleTime: 5_000,
  });
  const summary = useCloudEventSummary(taskId, enabled);
  const isLoading =
    liveFile.isLoading || (enabled && summary.toolCalls.size === 0);

  return useMemo(() => {
    if (!enabled) {
      return { content: null, touched: false, isLoading: false };
    }
    if (liveFile.data !== undefined) {
      return { content: liveFile.data, touched: true, isLoading: false };
    }
    const result = extractCloudFileContent(summary.toolCalls, filePath);
    return { ...result, isLoading };
  }, [enabled, summary, filePath, isLoading, liveFile.data]);
}
