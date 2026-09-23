import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { SignalReport } from "@posthog/shared/types";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef } from "react";

export function useTrackShortlistImpressions(reports: SignalReport[]) {
  const seen = useRef(new Set<string>());
  useEffect(() => {
    const fresh = reports.filter((report) => !seen.current.has(report.id));
    if (!fresh.length) return;
    fresh.forEach((report) => {
      seen.current.add(report.id);
    });
    track(ANALYTICS_EVENTS.INBOX_REPORTS_IMPRESSED, {
      inbox_client: "desktop",
      tab: "for_you_pilot",
      scope: "for-you",
      list_size: reports.length,
      total_count: null,
      has_active_filters: false,
      impression_count: fresh.length,
      impressions: fresh.map((report) => ({
        report_id: report.id,
        rank: reports.indexOf(report) + 1,
        priority: report.priority ?? null,
        actionability: report.actionability ?? null,
        status: report.status,
        is_suggested_reviewer: report.is_suggested_reviewer ?? false,
      })),
    });
  }, [reports]);
}
