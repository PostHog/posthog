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
import { useCompletedArtifactUploads } from "@posthog/ui/features/sessions/components/countArtifactUploads";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
import {
  keepPreviousData,
  type UseQueryResult,
  useQuery,
} from "@tanstack/react-query";

/**
 * A run's artifact manifest. The query key is shared across every caller, so a
 * message referencing several artifacts — or a message rendered next to the
 * Files list — costs one fetch rather than one per reference.
 *
 * The endpoint isn't pushed to, so the session's own count of finished
 * `upload_artifact` calls rides in the key: a file the agent just delivered
 * shows up now rather than on the next poll. It is derived here rather than
 * passed in, because a key one caller re-derives and another doesn't would
 * split the shared entry in two.
 */
export function useRunArtifacts(
  taskId: string | undefined,
  runId: string | undefined,
  options?: {
    enabled?: boolean;
    staleTime?: number;
    /** Poll interval while the run is still going; off by default. */
    refetchInterval?: number | false;
  },
): UseQueryResult<TaskRunArtifact[]> {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const events = useSessionSelector(taskId, (session) => session?.events);
  const completedUploads = useCompletedArtifactUploads(events ?? []);
  return useQuery({
    queryKey: [
      "cloudRunArtifacts",
      authIdentity,
      taskId,
      runId,
      completedUploads,
    ],
    queryFn: () =>
      sessionService.getCloudRunArtifacts(taskId ?? "", runId ?? ""),
    enabled:
      authIdentity !== null &&
      taskId !== undefined &&
      runId !== undefined &&
      (options?.enabled ?? true),
    retry: false,
    staleTime: options?.staleTime ?? Infinity,
    refetchInterval: options?.refetchInterval ?? false,
    // The upload count in the key means a finished upload lands every caller on
    // an empty cache entry. Carry the last manifest over it, or every artifact
    // already drawn blinks back to unresolved each time another one arrives.
    placeholderData: keepPreviousData,
  });
}
