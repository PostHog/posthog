import { buildResolveRequest } from "@posthog/core/inbox/bulkActions";
import type { InboxReportActionSurface } from "@posthog/shared/analytics-events";
import type { ResolveReasonOptionValue } from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import { taskFeedResultsQueryRoot } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import {
  ResolveReportDialog,
  type ResolveReportDialogResult,
} from "@posthog/ui/features/inbox/components/ResolveReportDialog";
import { reportKeys } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import {
  useReportActionResultTracker,
  useReportActionTracker,
} from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactElement, useCallback, useRef, useState } from "react";

export function useInboxReportResolveAction(
  report: SignalReport,
  surface: InboxReportActionSurface = "detail_pane",
  triageId?: string,
): {
  isPending: boolean;
  dialog: ReactElement | null;
  openDialog: (initialReason?: ResolveReasonOptionValue) => void;
  resolveWithReason: (reason: ResolveReasonOptionValue, note?: string) => void;
} {
  const [open, setOpen] = useState(false);
  const [initialReason, setInitialReason] =
    useState<ResolveReasonOptionValue>();
  const queryClient = useQueryClient();
  const fireAction = useReportActionTracker(report, surface, triageId);
  const trackResult = useReportActionResultTracker(report, surface, triageId);
  const inFlightRef = useRef(false);
  const startedAtRef = useRef<number | null>(null);
  const hasOpenPr =
    Boolean(report.implementation_pr_url) &&
    report.implementation_pr_merged !== true;
  const mutation = useAuthenticatedMutation(
    (client, result: ResolveReportDialogResult) =>
      client.updateSignalReportState(
        report.id,
        buildResolveRequest(result.reason, result.note),
      ),
    {
      onSuccess: async () => {
        if (startedAtRef.current !== null) {
          trackResult("resolve", "succeeded", startedAtRef.current);
        }
        await queryClient.invalidateQueries({
          queryKey: reportKeys.all,
          exact: false,
        });
        await queryClient.invalidateQueries({
          queryKey: taskFeedResultsQueryRoot,
          exact: false,
        });
        setOpen(false);
        toast.success(
          hasOpenPr
            ? "Report resolved. Closing its pull request."
            : "Report resolved",
        );
      },
      onError: (error) => {
        if (startedAtRef.current !== null) {
          trackResult(
            "resolve",
            "failed",
            startedAtRef.current,
            "request_failed",
          );
        }
        toast.error(error.message || "Failed to resolve report");
      },
      onSettled: () => {
        inFlightRef.current = false;
        startedAtRef.current = null;
      },
    },
  );

  const openDialog = useCallback((reason?: ResolveReasonOptionValue) => {
    setInitialReason(reason);
    setOpen(true);
  }, []);
  const resolveWithReason = useCallback(
    (reason: ResolveReasonOptionValue, note = "") => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      startedAtRef.current = Date.now();
      fireAction("resolve", { dismissal_reason: reason });
      mutation.mutate({ reason, note });
    },
    [fireAction, mutation],
  );
  const dialog = open ? (
    <ResolveReportDialog
      open={open}
      onOpenChange={setOpen}
      report={report}
      isSubmitting={mutation.isPending}
      initialReason={initialReason}
      onConfirm={(result) => resolveWithReason(result.reason, result.note)}
    />
  ) : null;

  return {
    isPending: mutation.isPending || inFlightRef.current,
    dialog,
    openDialog,
    resolveWithReason,
  };
}
