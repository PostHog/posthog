import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import { computeRefundEligibility } from "@posthog/core/inbox/refundEligibility";
import { SIGNALS_PR_REFUNDS_FLAG } from "@posthog/shared";
import type {
  SignalReport,
  SignalReportRefundReason,
} from "@posthog/shared/types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";

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

  const { canRefund, disabledReason } = computeRefundEligibility(
    report,
    flagEnabled,
  );

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
