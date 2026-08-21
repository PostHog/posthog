import type {
  InboxReportActionProperties,
  InboxReportActionSurface,
  InboxReportActionType,
} from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback } from "react";

type Extras = Partial<
  Omit<
    InboxReportActionProperties,
    | "report_id"
    | "report_title"
    | "report_age_hours"
    | "priority"
    | "actionability"
    | "action_type"
    | "surface"
    | "is_bulk"
    | "bulk_size"
    | "rank"
    | "list_size"
  >
>;

function reportAgeHours(report: SignalReport): number {
  const created = report.created_at ? new Date(report.created_at).getTime() : 0;
  if (!created) return 0;
  return Math.max(0, (Date.now() - created) / 36e5);
}

/**
 * Emits `INBOX_REPORT_ACTION` with the report identity pre-filled. Use on
 * detail screens where every interaction is single-report.
 */
export function useReportActionTracker(
  report: SignalReport,
  surface: InboxReportActionSurface = "detail_pane",
) {
  return useCallback(
    (action: InboxReportActionType, extras: Extras = {}) => {
      track(ANALYTICS_EVENTS.INBOX_REPORT_ACTION, {
        report_id: report.id,
        report_title: report.title ?? null,
        report_age_hours: reportAgeHours(report),
        priority: report.priority ?? null,
        actionability: report.actionability ?? null,
        action_type: action,
        surface,
        is_bulk: false,
        bulk_size: 1,
        rank: 0,
        list_size: 0,
        ...extras,
      });
    },
    [report, surface],
  );
}
