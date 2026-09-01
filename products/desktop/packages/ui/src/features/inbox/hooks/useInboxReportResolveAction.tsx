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
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactElement, useCallback, useState } from "react";

export function useInboxReportResolveAction(
  report: SignalReport,
  surface: InboxReportActionSurface = "detail_pane",
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
  const fireAction = useReportActionTracker(report, surface);
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
        toast.error(error.message || "Failed to resolve report");
      },
    },
  );

  const openDialog = useCallback((reason?: ResolveReasonOptionValue) => {
    setInitialReason(reason);
    setOpen(true);
  }, []);
  const resolveWithReason = useCallback(
    (reason: ResolveReasonOptionValue, note = "") => {
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
    isPending: mutation.isPending,
    dialog,
    openDialog,
    resolveWithReason,
  };
}
