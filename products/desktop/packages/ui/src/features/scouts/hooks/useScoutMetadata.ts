import type { ScoutMetadata } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

export function useScoutMetadata() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<ScoutMetadata | null>(
    scoutQueryKeys.metadata(projectId),
    (client) =>
      projectId ? client.getScoutMetadata(projectId) : Promise.resolve(null),
    { enabled: !!projectId, staleTime: 60_000 },
  );
}
