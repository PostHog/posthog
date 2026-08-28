import { reportAgeHours } from "@posthog/core/inbox/engagement";
import type {
  InboxReportActionSurface,
  InboxReportFeedbackSentiment,
} from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useMemo } from "react";

/** Bounded to keep the note within the analytics client's per-property limit. */
export const FEEDBACK_NOTE_MAX_LENGTH = 4000;

/**
 * Emits the report usefulness feedback events with the report identity
 * pre-filled. `rate` fires `INBOX_REPORT_FEEDBACK` on a thumb choice; `note`
 * fires `INBOX_REPORT_FEEDBACK_NOTE` for the optional follow-up note. Keeping
 * them as two calls preserves exactly one sentiment event per rating — the
 * note joins back to the rating on `report_id`.
 */
export function useReportFeedbackTracker(
  report: SignalReport,
  surface: InboxReportActionSurface = "detail_footer",
) {
  const base = useMemo(
    () => ({
      report_id: report.id,
      report_age_hours: reportAgeHours(report.created_at),
      priority: report.priority ?? null,
      actionability: report.actionability ?? null,
      has_pr: !!report.implementation_pr_url,
      surface,
    }),
    [report, surface],
  );

  const rate = useCallback(
    (sentiment: InboxReportFeedbackSentiment) => {
      track(ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK, { ...base, sentiment });
    },
    [base],
  );

  const note = useCallback(
    (sentiment: InboxReportFeedbackSentiment, text: string) => {
      track(ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK_NOTE, {
        ...base,
        sentiment,
        note: text.slice(0, FEEDBACK_NOTE_MAX_LENGTH),
      });
    },
    [base],
  );

  return { rate, note };
}
