import type { SignalTeamConfig } from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";

export function useSignalTeamConfig(options?: {
  enabled?: boolean;
  staleTime?: number;
}) {
  return useAuthenticatedQuery<SignalTeamConfig | null>(
    ["signals", "team-config"],
    async (client) => {
      try {
        return await client.getSignalTeamConfig();
      } catch {
        // Team config may not exist yet
        return null;
      }
    },
    {
      enabled: options?.enabled ?? true,
      staleTime: options?.staleTime ?? 30_000,
    },
  );
}
