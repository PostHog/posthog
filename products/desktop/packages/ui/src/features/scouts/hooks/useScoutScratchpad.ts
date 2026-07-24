import type { ScoutScratchpadEntry } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

/**
 * The scratchpad `list` endpoint caps at 500 newest-first entries with no
 * pagination wrapper, so pull the whole window in one read and group/search it
 * client-side. A team that routinely exceeds 500 notes would want the endpoint's
 * `date_to` cursor wired into a "load more" here.
 */
const SCRATCHPAD_FETCH_LIMIT = 500;

/**
 * The scout fleet's durable memory (`SignalScratchpad`) for the current project,
 * newest-first. Read-only: the harness writes these notes on internal scope; this
 * surface only inspects them. Backed by the same `/signals/scout/` endpoints as
 * the rest of the scouts UI.
 */
export function useScoutScratchpad() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<ScoutScratchpadEntry[]>(
    scoutQueryKeys.scratchpad(projectId),
    (client) =>
      projectId
        ? client.searchScoutScratchpad(projectId, {
            limit: SCRATCHPAD_FETCH_LIMIT,
          })
        : Promise.resolve([]),
    {
      enabled: !!projectId,
      staleTime: 30_000,
    },
  );
}
