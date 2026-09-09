import type { SignalReport } from "@posthog/shared/types";

// Copy per backend `refund_ineligibility_reason`. `already_refunded` and
// `billing_exempt` never reach the button (it is hidden for those), so only
// the two visible-but-ineligible reasons map here. The web inbox keeps the
// same table in `products/signals/frontend/inbox/utils/refundBlock.ts`.
const REFUND_BLOCKED_COPY: Record<string, string> = {
  out_of_period:
    "This PR was billed in an earlier billing period, so it can't be refunded here. Support can credit it back for you.",
  no_billable_pr: "This PR isn't billable, so there's nothing to refund.",
};

const REFUND_BLOCKED_FALLBACK_COPY = "This PR can't be refunded right now.";

// Reasons a person can still act on. The refund window is the org's billing
// period, so a PR billed before it needs a billing-service credit, which only
// support can issue. Every other reason has no next step.
const REFUND_SUPPORT_ROUTE_REASONS = new Set(["out_of_period"]);

export interface RefundEligibility {
  canRefund: boolean;
  disabledReason: string | null;
  /** The backend reason, when the report is offered but can't be refunded. */
  blockedReason: string | null;
  /** True when support can still credit this PR back, so the reader has a next step. */
  hasSupportRoute: boolean;
}

/**
 * Decide whether the refund control shows (`canRefund`) and, when it shows but
 * the backend already knows it can't be refunded right now, the copy to display
 * (`disabledReason`). The button is offered only when the flag is on and the
 * report has a billable PR that hasn't been refunded; the server enforces the
 * same rules, so this is a display gate.
 *
 * `hasSupportRoute` tells a surface that can open a support request to offer
 * that instead of a disabled button.
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

  const blockedReason = canRefund
    ? (report.refund_ineligibility_reason ?? null)
    : null;

  return {
    canRefund,
    disabledReason: blockedReason
      ? (REFUND_BLOCKED_COPY[blockedReason] ?? REFUND_BLOCKED_FALLBACK_COPY)
      : null,
    blockedReason,
    hasSupportRoute:
      blockedReason !== null && REFUND_SUPPORT_ROUTE_REASONS.has(blockedReason),
  };
}
