import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

// Once per app session is the whole debounce. The canonical fleet only changes
// on a deploy, and a scout the person creates lands in the list on its own, so
// re-running the reconcile every time they reopen the section buys nothing.
const FLEET_SYNC_STALE_MS = 60 * 60_000;

/**
 * Materializes the project's scout fleet when the scouts section opens. A
 * project the Temporal coordinator never reached has no scout configs at all,
 * so without this the section shows an empty fleet no matter how long you wait.
 *
 * The endpoint answers with the fleet it just materialized, which the hook
 * writes into the cache `useScoutConfigs` reads. That keeps one source of truth
 * for the fleet, and saves the section from waiting out a poll cycle to show
 * the scouts that were just created.
 */
export function useScoutFleetSync(): {
  /** False once the first sync settles, success or failure. */
  isSyncing: boolean;
} {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const queryClient = useQueryClient();
  const { data, isLoading } = useAuthenticatedQuery<ScoutConfig[]>(
    scoutQueryKeys.fleetSync(projectId),
    (client) =>
      projectId ? client.syncScoutConfigs(projectId) : Promise.resolve([]),
    {
      enabled: !!projectId,
      staleTime: FLEET_SYNC_STALE_MS,
      gcTime: FLEET_SYNC_STALE_MS,
      refetchOnWindowFocus: false,
      // A member without write access gets a 403 here, which retrying can't fix.
      // The list query is what keeps the section usable for them.
      retry: false,
    },
  );

  useEffect(() => {
    if (!data || !projectId) return;
    queryClient.setQueryData(scoutQueryKeys.configs(projectId), data);
  }, [data, projectId, queryClient]);

  // `isLoading`, not `isPending`: a query the hook disables (signed out, no
  // project) stays pending forever, and reading that as "still syncing" would
  // hold the section under a skeleton it can never leave.
  return { isSyncing: isLoading };
}
