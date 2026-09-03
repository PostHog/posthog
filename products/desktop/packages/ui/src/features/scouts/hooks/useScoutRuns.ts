import {
  fetchScoutRunsWindow,
  type ScoutRunsWindow,
} from "@posthog/core/scouts/scoutRunsWindow";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import {
  readQuerySnapshot,
  useWriteQuerySnapshot,
} from "@posthog/ui/hooks/useQuerySnapshot";
import type { UseQueryResult } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

/**
 * Fleet-wide scout runs from the recent window (newest first), assembled in
 * core by walking the backend's 100-row pages. The backend has no per-scout
 * filter yet (scouts-ui api gap 1), so per-scout views filter this window
 * client-side. `complete` is false if pagination had to stop early.
 *
 * A first load publishes the first page as soon as it lands, so the newest runs
 * are on screen after one round trip instead of after the last one. A load over
 * runs already on screen swaps them in one step, so the list never shrinks.
 */
export function useScoutRuns() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const queryClient = useQueryClient();
  const queryKey = scoutQueryKeys.runs(projectId);
  const snapshot = `scouts.runs.${projectId ?? "none"}`;
  const query = useAuthenticatedQuery<ScoutRunsWindow>(
    queryKey,
    (client) => {
      if (!projectId) return Promise.resolve({ runs: [], complete: true });
      let published =
        queryClient.getQueryData<ScoutRunsWindow>(queryKey) !== undefined;
      return fetchScoutRunsWindow(client, projectId, new Date(), (partial) => {
        // The newest runs sit in the first page. Publishing that one page fills
        // the screen; publishing every page would make each view that reads the
        // window fetch again for each one.
        if (published) return;
        published = true;
        queryClient.setQueryData(queryKey, partial);
      });
    },
    {
      enabled: !!projectId,
      staleTime: 15_000,
      refetchInterval: 60_000,
      initialData: () => readQuerySnapshot<ScoutRunsWindow>(snapshot),
      initialDataUpdatedAt: 0,
    },
  );
  useWriteQuerySnapshot(snapshot, query.data, !query.isFetching);
  return query;
}

/**
 * True while pages are still coming in behind the runs already on screen. The
 * run counts and the empty states are not final until this is false.
 */
export function isRunsWindowLoadingMore(
  query: UseQueryResult<ScoutRunsWindow>,
): boolean {
  return query.isFetching && !(query.data?.complete ?? false);
}
