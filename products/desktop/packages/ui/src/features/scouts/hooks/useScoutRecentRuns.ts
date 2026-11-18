import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

export function useScoutRecentRuns() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery(
    [...scoutQueryKeys.runs(projectId), "recent-per-scout"],
    (client) =>
      projectId ? client.listRecentScoutRuns(projectId) : Promise.resolve([]),
    { enabled: !!projectId, staleTime: 30_000, refetchInterval: 60_000 },
  );
}

export function useScoutOutputSummary() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery(
    [...scoutQueryKeys.runs(projectId), "output-summary"],
    (client) =>
      projectId
        ? client.getScoutOutputSummary(projectId)
        : Promise.resolve(null),
    { enabled: !!projectId, staleTime: 30_000, refetchInterval: 60_000 },
  );
}
