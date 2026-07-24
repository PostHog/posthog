import {
  type CloudFileContent,
  extractCloudFileContent,
} from "@posthog/core/task-detail/cloudToolChanges";
import { useMemo } from "react";
import { useCloudEventSummary } from "../../task-detail/hooks/useCloudEventSummary";

export type CloudFileResult = CloudFileContent & { isLoading: boolean };

export function useCloudFileContent(
  taskId: string,
  filePath: string,
  enabled: boolean,
): CloudFileResult {
  const summary = useCloudEventSummary(taskId, enabled);
  const isLoading = enabled && summary.toolCalls.size === 0;

  return useMemo(() => {
    if (!enabled) {
      return { content: null, touched: false, isLoading: false };
    }
    const result = extractCloudFileContent(summary.toolCalls, filePath);
    return { ...result, isLoading };
  }, [enabled, summary, filePath, isLoading]);
}
