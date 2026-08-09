import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import { SIGNALS_PR_REFUNDS_FLAG } from "@posthog/shared";
import type {
  SignalReport,
  SignalReportRefundReason,
} from "@posthog/shared/types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";

// Copy per backend `refund_ineligibility_reason`. `already_refunded` and
// `billing_exempt` never reach the button (it is hidden for those), so only
// the two visible-but-ineligible reasons map here.
const REFUND_DISABLED_REASONS: Record<string, string> = {
  out_of_period:
    "This PR was billed in a previous billing period and can no longer be refunded.",
  no_billable_pr: "This PR isn't billable, so there's nothing to refund.",
};

/**
 * Refund-and-archive a report's PR, mirroring the web inbox. The button is
 * offered only when the flag is on and the report has a billable PR that
 * hasn't been refunded; the server enforces the same rules, so `canRefund`
 * is a display gate.
 */
export function useRefundReport(report: SignalReport) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const flagEnabled = useFeatureFlag(SIGNALS_PR_REFUNDS_FLAG);

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

  const mutation = useMutation({
    mutationFn: (input: { reason: SignalReportRefundReason; note?: string }) =>
      client.refundSignalReport(report.id, input),
    onSuccess: () => {
      toast.success("PR refunded. The report has been archived.");
      queryClient.invalidateQueries({ queryKey: inboxReportKeys.all });
    },
    onError: (error) => {
      toast.error(
        error instanceof Error ? error.message : "Couldn't refund this PR.",
      );
    },
  });

  return { canRefund, disabledReason, mutation };
}
