import type { SignalReportRefundReason } from "./domain-types";

/**
 * Canonical refund reasons shown when refunding a report's PR. Values are
 * persisted on the refund; edit the list here only.
 */
export const REFUND_REASON_OPTIONS: readonly {
  value: SignalReportRefundReason;
  label: string;
}[] = [
  {
    value: "pr_incorrect",
    label: "The PR doesn't fix what the report describes",
  },
  { value: "pr_not_useful", label: "The PR works but is not useful to me" },
  { value: "duplicate", label: "Duplicate of work already covered" },
  { value: "other", label: "Something else…" },
];
