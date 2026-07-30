import {
  fetchScoutRunsWindow,
  type ScoutRunsWindow,
} from "@posthog/core/scouts/scoutRunsWindow";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

/**
 * Fleet-wide scout runs from the recent window (newest first), assembled in
 * core by walking the backend's 100-row pages. The backend has no per-scout
 * filter yet (scouts-ui api gap 1), so per-scout views filter this window
 * client-side. `complete` is false if pagination had to stop early.
 */
export function useScoutRuns() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<ScoutRunsWindow>(
    scoutQueryKeys.runs(projectId),
    (client) =>
      projectId
        ? fetchScoutRunsWindow(client, projectId)
        : Promise.resolve({ runs: [], complete: true }),
    {
      enabled: !!projectId,
      staleTime: 15_000,
      refetchInterval: 60_000,
    },
  );
}
