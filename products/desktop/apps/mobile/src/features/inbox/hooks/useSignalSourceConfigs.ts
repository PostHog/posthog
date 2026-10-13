import type { SignalSourceConfig } from "@posthog/api-client/posthog-client";
import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@/features/auth";
import { getPostHogApiClient } from "@/lib/posthogApiClient";

export function useSignalSourceConfigs() {
  const { projectId, oauthAccessToken } = useAuthStore();

  return useQuery<SignalSourceConfig[]>({
    queryKey: ["inbox", "signal-source-configs", projectId],
    queryFn: () =>
      projectId
        ? getPostHogApiClient().listSignalSourceConfigs(projectId)
        : Promise.resolve([]),
    enabled: !!projectId && !!oauthAccessToken,
    staleTime: 30_000,
  });
}
