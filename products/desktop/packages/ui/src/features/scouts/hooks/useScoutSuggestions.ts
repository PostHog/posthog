import type { ScoutSuggestionSet } from "@posthog/api-client/posthog-client";
import { SCOUTS_SUGGESTIONS_UI_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

/** How often the batch is re-read while a scan runs. A scan takes minutes, not seconds. */
const SCAN_POLL_INTERVAL_MS = 15_000;

/**
 * The project's pre-computed scout suggestions. Off the flag nothing is read,
 * so a project without the surface never pays for the request.
 *
 * `isScanning` puts the query on a poll: a refresh runs headlessly, and the new
 * batch only shows up when the read picks it up.
 */
export function useScoutSuggestions({ isScanning = false } = {}) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const enabled = useFeatureFlag(SCOUTS_SUGGESTIONS_UI_FLAG);
  return useAuthenticatedQuery<ScoutSuggestionSet | null>(
    scoutQueryKeys.suggestions(projectId),
    (client) =>
      projectId
        ? client.listScoutSuggestions(projectId)
        : Promise.resolve(null),
    {
      enabled: enabled && !!projectId,
      staleTime: 60_000,
      refetchInterval: isScanning ? SCAN_POLL_INTERVAL_MS : false,
      // A member without the scout scopes gets a 403 here, which retrying
      // cannot fix, and the roster stays usable without the picks.
      retry: false,
    },
  );
}
