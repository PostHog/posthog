import {
  type InboxDetailTab,
  inboxDetailTabReports,
  reportAgeHours,
} from "@posthog/core/inbox/engagement";
import type { InboxReportCloseMethod } from "@posthog/shared/analytics-events";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { SignalReport } from "@posthog/shared/types";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef } from "react";

export type { InboxDetailTab };

/**
 * Last report id opened during the current inbox visit, used to populate
 * `previous_report_id` on the next `INBOX_REPORT_OPENED`. Module-scoped so it
 * survives the detail screen unmounting between reports, but reset per visit
 * via {@link resetReportOpenTrackerHistory} so report-to-report navigation
 * pairs never span separate visits.
 */
let lastOpenedReportId: string | null = null;

/**
 * Clears the cross-report navigation history. Call when the inbox shell mounts
 * so the first report opened in a new visit reports `previous_report_id: null`.
 */
export function resetReportOpenTrackerHistory(): void {
  lastOpenedReportId = null;
}

/**
 * Fires `INBOX_REPORT_OPENED` when a detail screen mounts (or switches to a new
 * report) and `INBOX_REPORT_CLOSED` with the dwell time when it closes.
 *
 * Restores the open/close engagement events dropped when Inbox 2.0 deleted
 * `useInboxEngagementTracker`. Driven by the detail route lifecycle via
 * `InboxReportDetailGate`, so it covers reports, pull requests, and runs.
 *
 * `rank` / `list_size` mirror the originating tab's membership: the Runs tab is
 * project-wide (`ignoreScope`/`ignoreFilters`), while the Pull requests and
 * Reports tabs use the scoped/filtered list — so a report's rank is measured
 * against the list it was actually opened from.
 *
 * `open_method` and `scrolled` are not yet wired in the route-based UI (the v1
 * open-method plumbing and scroll tracker were removed), so they report
 * "unknown" and `false` respectively.
 */
export function useReportOpenTracker(
  report: SignalReport,
  tab: InboxDetailTab,
): void {
  // Mount only the query matching the originating tab so rank is relative to the
  // rows the user actually saw (and so a non-run detail doesn't start the unused
  // project-wide poll alongside the scoped one):
  //   - Runs tab is project-wide (ignoreScope/ignoreFilters).
  //   - Pull requests tab renders the server-filtered PR-only list, so mirror
  //     that here — otherwise a PR past the broad list's first page would get
  //     rank -1 and a list_size from the broad list, not the rows shown.
  //   - Reports tab renders the scoped+filtered broad list.
  const { scopedReports } = useInboxAllReports(
    tab === "runs"
      ? { ignoreScope: true, ignoreFilters: true }
      : tab === "pulls"
        ? { pullRequestsOnly: true }
        : undefined,
  );
  const visible = inboxDetailTabReports(tab, scopedReports);

  // Keep the visible list reachable from the mount effect without making the
  // effect re-run (and thus re-fire OPENED) on every list refetch.
  const visibleRef = useRef(visible);
  visibleRef.current = visible;

  // Snapshot report fields so the close cleanup reports the values as they were
  // at open time, not whatever the prop is at teardown.
  const reportRef = useRef(report);
  reportRef.current = report;

  // Detect a report→report switch during render so the close cleanup can label
  // it `next_report` rather than `navigated_away`. Writing a ref during render
  // is the React-sanctioned "track the previous prop" pattern, and crucially it
  // runs before the outgoing effect's cleanup, which is where we read it.
  const renderedIdRef = useRef<string | null>(null);
  const closeMethodRef = useRef<InboxReportCloseMethod>("navigated_away");
  if (renderedIdRef.current !== null && renderedIdRef.current !== report.id) {
    closeMethodRef.current = "next_report";
  }
  renderedIdRef.current = report.id;

  // biome-ignore lint/correctness/useExhaustiveDependencies: report.id is the trigger — the detail route stays mounted across report→report navigation, so we re-bracket OPENED/CLOSED on id change while reading the rest from refs.
  useEffect(() => {
    const openedAt = Date.now();
    const opened = reportRef.current;
    const list = visibleRef.current;
    const rank = list.findIndex((r) => r.id === opened.id);

    track(ANALYTICS_EVENTS.INBOX_REPORT_OPENED, {
      report_id: opened.id,
      report_title: opened.title ?? null,
      report_age_hours: reportAgeHours(opened.created_at),
      status: opened.status ?? null,
      priority: opened.priority ?? null,
      actionability: opened.actionability ?? null,
      source_products: opened.source_products ?? [],
      rank,
      list_size: list.length,
      open_method: "unknown",
      previous_report_id: lastOpenedReportId,
    });
    lastOpenedReportId = opened.id;

    return () => {
      track(ANALYTICS_EVENTS.INBOX_REPORT_CLOSED, {
        report_id: opened.id,
        report_title: opened.title ?? null,
        report_age_hours: reportAgeHours(opened.created_at),
        priority: opened.priority ?? null,
        actionability: opened.actionability ?? null,
        time_spent_ms: Date.now() - openedAt,
        scrolled: false,
        close_method: closeMethodRef.current,
      });
      // Reset to the exit default; a subsequent switch re-sets it during render.
      closeMethodRef.current = "navigated_away";
    };
  }, [report.id]);
}
