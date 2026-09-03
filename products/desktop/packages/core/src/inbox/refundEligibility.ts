import type { SignalReport } from "@posthog/shared/types";

// Copy per backend `refund_ineligibility_reason`. `already_refunded` and
// `billing_exempt` never reach the button (it is hidden for those), so only
// the two visible-but-ineligible reasons map here.
const REFUND_DISABLED_REASONS: Record<string, string> = {
  out_of_period:
    "This PR was billed in a previous billing period and can no longer be refunded.",
  no_billable_pr: "This PR isn't billable, so there's nothing to refund.",
};

export interface RefundEligibility {
  canRefund: boolean;
  disabledReason: string | null;
}

/**
 * Decide whether the refund control shows (`canRefund`) and, when it shows but
 * the backend already knows it can't be refunded right now, the copy to display
 * (`disabledReason`). The button is offered only when the flag is on and the
 * report has a billable PR that hasn't been refunded; the server enforces the
 * same rules, so this is a display gate.
 */
export function computeRefundEligibility(
  report: SignalReport,
  flagEnabled: boolean,
): RefundEligibility {
  const canRefund =
    flagEnabled &&
    !!report.implementation_pr_url &&
    !report.refund &&
    !report.billing_exempt_reason;

  const disabledReason =
    canRefund && report.refund_ineligibility_reason
      ? (REFUND_DISABLED_REASONS[report.refund_ineligibility_reason] ??
        "This PR can't be refunded right now.")
      : null;

  return { canRefund, disabledReason };
}
