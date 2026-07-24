import { buildInboxViewedProperties } from "@posthog/core/inbox/engagement";
import { INBOX_SCOPE_FOR_YOU } from "@posthog/core/inbox/reportMembership";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef } from "react";

/**
 * Fires `INBOX_VIEWED` once per inbox visit, after the report list settles,
 * with the counts the user sees on load (tab badges, total, ready, and the
 * priority/actionability breakdown of the visible reports).
 *
 * Restores the event dropped when Inbox 2.0 deleted `InboxSignalsTab`. Mounted
 * from `InboxView`, so it fires once per visit and survives tab switches (the
 * shell stays mounted while the `<Outlet />` swaps tab bodies).
 */
export function useTrackInboxViewed(): void {
  const {
    scopedReports,
    totalCount,
    counts,
    scope,
    isSuccess,
    sourceProductFilter,
    priorityFilter,
    searchQuery,
  } = useInboxAllReports();

  const firedRef = useRef(false);
  useEffect(() => {
    if (firedRef.current) return;
    // Gate on a successful load, not just `!isLoading`: an errored initial
    // request also leaves `isLoading` false with an empty list, and `firedRef`
    // would then lock in a bogus empty-inbox view that a later refetch can't fix.
    if (!isSuccess) return;
    firedRef.current = true;
    track(
      ANALYTICS_EVENTS.INBOX_VIEWED,
      buildInboxViewedProperties({
        visibleReports: scopedReports,
        totalCount,
        tabCounts: counts,
        filters: {
          sourceProductFilter,
          priorityFilter,
          searchQuery,
          isDefaultScope: scope === INBOX_SCOPE_FOR_YOU,
        },
      }),
    );
  }, [
    isSuccess,
    scopedReports,
    totalCount,
    counts,
    scope,
    sourceProductFilter,
    priorityFilter,
    searchQuery,
  ]);
}
