import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

export function useScoutConfigs() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<ScoutConfig[]>(
    scoutQueryKeys.configs(projectId),
    (client) =>
      projectId ? client.listScoutConfigs(projectId) : Promise.resolve([]),
    { enabled: !!projectId, staleTime: 30_000 },
  );
}
