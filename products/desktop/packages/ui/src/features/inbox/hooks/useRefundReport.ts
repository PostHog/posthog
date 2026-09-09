import { reportAgeHours } from "@posthog/core/inbox/engagement";
import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import { computeRefundEligibility } from "@posthog/core/inbox/refundEligibility";
import { ANALYTICS_EVENTS, SIGNALS_PR_REFUNDS_FLAG } from "@posthog/shared";
import type {
  SignalReport,
  SignalReportRefundReason,
} from "@posthog/shared/types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { inboxReportSupportUrl } from "@posthog/ui/utils/posthogLinks";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";

/**
 * Refund-and-archive a report's PR, mirroring the web inbox. The button is
 * offered only when the flag is on and the report has a billable PR that
 * hasn't been refunded; the server enforces the same rules, so `canRefund`
 * is a display gate.
 *
 * When the backend already refuses the refund, `hasSupportRoute` says whether
 * support can still credit the PR back, and `requestSupportCredit` opens that
 * request. The blocked state reports itself to analytics when it renders,
 * because a disabled control is never clicked.
 */
export function useRefundReport(report: SignalReport) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const flagEnabled = useFeatureFlag(SIGNALS_PR_REFUNDS_FLAG);
  const trackAction = useReportActionTracker(report);

  const { canRefund, disabledReason, blockedReason, hasSupportRoute } =
    computeRefundEligibility(report, flagEnabled);

  // Deps are the identity of that state, so a refetch of the same report stays
  // one event.
  // biome-ignore lint/correctness/useExhaustiveDependencies: the report's other fields ride along; they must not re-fire the event
  useEffect(() => {
    if (!blockedReason) {
      return;
    }
    track(ANALYTICS_EVENTS.INBOX_REPORT_REFUND_BLOCKED, {
      report_id: report.id,
      report_age_hours: reportAgeHours(report.created_at),
      priority: report.priority ?? null,
      actionability: report.actionability ?? null,
      reason: blockedReason,
      has_support_route: hasSupportRoute,
      surface: "detail_pane",
    });
  }, [report.id, blockedReason, hasSupportRoute]);

  const requestSupportCredit = useCallback(() => {
    const url = inboxReportSupportUrl(report.id);
    if (!url) {
      toast.error(
        "Couldn't open support from here. Ask for a credit from the PostHog app.",
      );
      return;
    }
    trackAction("refund_support");
    openExternalUrl(url);
  }, [report.id, trackAction]);

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

  return {
    canRefund,
    disabledReason,
    hasSupportRoute,
    requestSupportCredit,
    mutation,
  };
}
