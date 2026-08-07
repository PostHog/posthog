import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import type { TaskRunArtifact } from "@posthog/shared";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { type UseQueryResult, useQuery } from "@tanstack/react-query";

/**
 * A run's artifact manifest. The query key is shared across every caller, so a
 * message referencing several artifacts — or a message rendered next to the
 * Files list — costs one fetch rather than one per reference.
 */
export function useRunArtifacts(
  taskId: string | undefined,
  runId: string | undefined,
  options?: { enabled?: boolean; staleTime?: number },
): UseQueryResult<TaskRunArtifact[]> {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  return useQuery({
    queryKey: ["cloudRunArtifacts", authIdentity, taskId, runId],
    queryFn: () =>
      sessionService.getCloudRunArtifacts(taskId ?? "", runId ?? ""),
    enabled:
      authIdentity !== null &&
      taskId !== undefined &&
      runId !== undefined &&
      (options?.enabled ?? true),
    retry: false,
    staleTime: options?.staleTime ?? Infinity,
  });
}
