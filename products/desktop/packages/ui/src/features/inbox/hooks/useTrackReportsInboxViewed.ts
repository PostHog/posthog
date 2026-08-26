import { buildInboxViewedProperties } from "@posthog/core/inbox/engagement";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { SignalReport } from "@posthog/shared/types";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef } from "react";

export function useTrackReportsInboxViewed({
  reports,
  totalCount,
  isReady,
  sourceProductFilter,
  priorityFilter,
  searchQuery,
  isDefaultScope,
}: {
  reports: SignalReport[];
  totalCount: number;
  isReady: boolean;
  sourceProductFilter: string[];
  priorityFilter: string[];
  searchQuery: string;
  isDefaultScope: boolean;
}): void {
  const firedRef = useRef(false);

  useEffect(() => {
    if (!isReady || firedRef.current) return;
    firedRef.current = true;
    track(
      ANALYTICS_EVENTS.INBOX_VIEWED,
      buildInboxViewedProperties({
        visibleReports: reports,
        totalCount,
        filters: {
          surface: "desktop",
          sourceProductFilter,
          priorityFilter,
          searchQuery,
          isDefaultScope,
        },
      }),
    );
  }, [
    reports,
    totalCount,
    isReady,
    sourceProductFilter,
    priorityFilter,
    searchQuery,
    isDefaultScope,
  ]);
}
