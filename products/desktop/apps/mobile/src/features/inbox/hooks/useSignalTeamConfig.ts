import type { SignalTeamConfig } from "@posthog/shared/domain-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/features/auth";
import { getPostHogApiClient } from "@/lib/posthogApiClient";

function teamConfigKey(projectId: number | null) {
  return ["signals", "team-config", projectId] as const;
}

export function useSignalTeamConfig() {
  const { projectId, oauthAccessToken } = useAuthStore();

  // The backend lazily creates the singleton, so a read never means "no config".
  // Let auth/5xx/network failures surface as query errors instead of a false
  // no-cap state.
  return useQuery<SignalTeamConfig>({
    queryKey: teamConfigKey(projectId),
    queryFn: () => getPostHogApiClient().getSignalTeamConfig(),
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
      queryClient.setQueryData<SignalTeamConfig>(
        teamConfigKey(projectId),
        fresh,
      );
    },
  });
}
