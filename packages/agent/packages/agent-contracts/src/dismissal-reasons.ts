/**
 * Canonical dismiss / suppress reasons shown in the app. Values are persisted on dismissal artefacts.
 * Types are derived from this list — add or reorder options here only.
 */
export const DISMISSAL_REASON_OPTIONS = [
  {
    value: "already_fixed",
    label: "Already fixed",
    snoozesInsteadOfDismiss: true,
  },
  {
    value: "report_unclear",
    label: "Report is unclear to me",
  },
  {
    value: "analysis_wrong",
    label: "Agent's analysis is wrong",
  },
  {
    value: "wrong_assignee",
    label: "Wrong assignee",
  },
  {
    value: "wontfix_intentional",
    label: "Won't fix - intentional behavior",
  },
  {
    value: "wontfix_irrelevant",
    label: "Not relevant to this project",
  },
  { value: "other", label: "Something else…" },
] as const;

export const RESOLVE_REASON_OPTIONS = [
  { value: "fixed_outside_posthog", label: "Implemented manually" },
  { value: "no_action_needed", label: "No action needed" },
  { value: "already_fixed", label: "Was already fixed before this report" },
  { value: "other", label: "Something else…" },
] as const;

/** Persisted dismissal / suppress reason (values match {@link DISMISSAL_REASON_OPTIONS}). */
export type DismissalReasonOptionValue =
  (typeof DISMISSAL_REASON_OPTIONS)[number]["value"];

export type ResolveReasonOptionValue =
  (typeof RESOLVE_REASON_OPTIONS)[number]["value"];

export type ReportStateReason =
  | DismissalReasonOptionValue
  | ResolveReasonOptionValue
  | "verified_manually"
  | "pr_merged";

/** Whether the given reason snoozes the report (temporarily) instead of permanently dismissing it. */
export function isDismissalReasonSnooze(
  value: DismissalReasonOptionValue,
): boolean {
  const option = DISMISSAL_REASON_OPTIONS.find((o) => o.value === value);
  return (
    option != null &&
    "snoozesInsteadOfDismiss" in option &&
    option.snoozesInsteadOfDismiss === true
  );
}

/**
 * Human label for a persisted dismissal reason code. Reason codes are owned by
 * the client that dismissed the report, so an unrecognised value (e.g. from a
 * newer client) falls back to the raw code rather than being dropped.
 */
export function dismissalReasonLabel(value: string): string {
  return (
    DISMISSAL_REASON_OPTIONS.find((o) => o.value === value)?.label ??
    RESOLVE_REASON_OPTIONS.find((o) => o.value === value)?.label ??
    (value === "verified_manually" ? "Verified manually" : undefined) ??
    (value === "pr_merged" ? "PR already merged" : value)
  );
}
