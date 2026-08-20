import type { SignalTeamConfig } from "@posthog/shared/domain-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/features/auth";
import { getPostHogApiClient } from "@/lib/posthogApiClient";

function teamConfigKey(projectId: number | null) {
  return ["signals", "team-config", projectId] as const;
}

export function useSignalTeamConfig() {
  const { projectId, oauthAccessToken } = useAuthStore();

  return useQuery<SignalTeamConfig | null>({
    queryKey: teamConfigKey(projectId),
    queryFn: async () => {
      try {
        return await getPostHogApiClient().getSignalTeamConfig();
      } catch {
        // The team config row may not exist yet.
        return null;
      }
    },
    enabled: !!projectId && !!oauthAccessToken,
    staleTime: 30_000,
  });
}

/** Save (`number`) or clear (`null`) the per-project daily report cap. */
export function useUpdateMaxReportsPerDay() {
  const { projectId } = useAuthStore();
  const queryClient = useQueryClient();

  return useMutation<SignalTeamConfig, Error, number | null>({
    mutationFn: (limit) =>
      getPostHogApiClient().updateSignalTeamConfig({
        max_reports_per_day: limit,
      }),
    onSuccess: (fresh) => {
      queryClient.setQueryData<SignalTeamConfig | null>(
        teamConfigKey(projectId),
        fresh,
      );
    },
  });
}
