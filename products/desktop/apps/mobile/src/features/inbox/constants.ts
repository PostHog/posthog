/** Comma-separated statuses for the inbox pipeline (excludes terminal/deleted). */
export const INBOX_PIPELINE_STATUS_FILTER =
  "potential,candidate,in_progress,ready,pending_input";

/**
 * Status filter for the Archive view — the two terminal, not-in-inbox states:
 * `suppressed` (user archived it; restorable) and `resolved` (its
 * implementation PR merged; terminal, reference only).
 */
export const INBOX_DISMISSED_STATUS_FILTER = "suppressed,resolved";

/** Polling interval for inbox queries (ms). */
export const INBOX_REFETCH_INTERVAL_MS = 5_000;

/**
 * Reasons offered when the user dismisses a signal report.
 * Mirrors apps/code/src/shared/dismissalReasons.ts.
 */
export const DISMISSAL_REASON_OPTIONS = [
  {
    value: "already_fixed",
    label: "Already fixed",
    snoozesInsteadOfDismiss: true,
  },
  { value: "report_unclear", label: "Report is unclear to me" },
  { value: "analysis_wrong", label: "Agent's analysis is wrong" },
  { value: "wontfix_intentional", label: "Won't fix — intentional behavior" },
  {
    value: "wontfix_irrelevant",
    label: "Won't fix — issue is real but insignificant",
  },
  { value: "other", label: "Something else…" },
] as const;

export type DismissalReasonOptionValue =
  (typeof DISMISSAL_REASON_OPTIONS)[number]["value"];
