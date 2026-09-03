import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { getScoutOrigin } from "@posthog/core/scouts/scoutPresentation";
import type { ScoutFleetSyncOutcome } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef } from "react";

export function useTrackFleetViewed(
  configs: ScoutConfig[],
  syncOutcome: ScoutFleetSyncOutcome | null,
) {
  const tracked = useRef(false);
  useEffect(() => {
    // Wait for the sync to settle, so a fleet the sync is about to change is
    // never reported against an outcome the request has not reached yet.
    if (tracked.current || syncOutcome === null) return;
    tracked.current = true;
    track(ANALYTICS_EVENTS.SCOUT_FLEET_VIEWED, {
      scout_count: configs.length,
      enabled_count: configs.filter((config) => config.enabled).length,
      dry_run_count: configs.filter((config) => !config.emit).length,
      custom_count: configs.filter(
        (config) => getScoutOrigin(config) === "custom",
      ).length,
      is_empty: configs.length === 0,
      sync_outcome: syncOutcome,
    });
  }, [configs, syncOutcome]);
}
