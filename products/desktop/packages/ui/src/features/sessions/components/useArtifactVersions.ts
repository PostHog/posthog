import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery } from "@tanstack/react-query";

export function useArtifactVersions(
  taskId: string,
  artifactId: string,
  enabled = true,
) {
  const service = useService<SessionService>(SESSION_SERVICE);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  return useQuery({
    queryKey: ["artifactVersions", authIdentity, taskId, artifactId],
    queryFn: () => service.getCloudArtifactVersions(taskId, artifactId),
    enabled: authIdentity !== null && enabled,
    staleTime: 3_000,
    meta: AUTH_SCOPED_QUERY_META,
  });
}
