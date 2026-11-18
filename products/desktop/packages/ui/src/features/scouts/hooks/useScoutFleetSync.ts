import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { ScoutRequestError } from "@posthog/api-client/posthog-client";
import type { ScoutFleetSyncOutcome } from "@posthog/shared";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

// Once per app session is the whole debounce. The canonical fleet only changes
// on a deploy, and a scout the person creates lands in the list on its own, so
// re-running the reconcile every time they reopen the section buys nothing.
const FLEET_SYNC_STALE_MS = 60 * 60_000;

// A refused sync leaves the section on whatever the list query returned, so the
// fleet on screen can be stale (403, a member without write access) or from
// another project (404, a stale project id) with nothing on screen saying so.
// The outcome rides on `Scout fleet viewed` to keep those apart. Null while the
// sync is still in flight, so a view is never reported against an outcome the
// request has not reached yet.
function syncOutcomeFor(
  isSyncing: boolean,
  isPending: boolean,
  error: Error | null,
): ScoutFleetSyncOutcome | null {
  if (isSyncing) return null;
  if (error instanceof ScoutRequestError) {
    if (error.status === 403) return "skipped_permission";
    if (error.status === 404) return "not_found";
    return "failed";
  }
  if (error) return "failed";
  // A query the hook disables (signed out, no project) settles pending, and no
  // sync was ever issued for it.
  return isPending ? "not_attempted" : "synced";
}

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
  /** How that sync ended, for the `Scout fleet viewed` event. Null until it settles. */
  syncOutcome: ScoutFleetSyncOutcome | null;
} {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const queryClient = useQueryClient();
  const { data, isLoading, isPending, error } = useAuthenticatedQuery<
    ScoutConfig[]
  >(
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
  return {
    isSyncing: isLoading,
    syncOutcome: syncOutcomeFor(isLoading, isPending, error),
  };
}
