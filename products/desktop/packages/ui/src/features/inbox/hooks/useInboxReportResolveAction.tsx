import { buildResolveRequest } from "@posthog/core/inbox/bulkActions";
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

export function useInboxReportResolveAction(report: SignalReport): {
  isPending: boolean;
  dialog: ReactElement | null;
  openDialog: () => void;
} {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const fireAction = useReportActionTracker(report);
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

  const openDialog = useCallback(() => setOpen(true), []);
  const dialog = open ? (
    <ResolveReportDialog
      open={open}
      onOpenChange={setOpen}
      report={report}
      isSubmitting={mutation.isPending}
      onConfirm={(result) => {
        fireAction("resolve", { dismissal_reason: result.reason });
        mutation.mutate(result);
      }}
    />
  ) : null;

  return { isPending: mutation.isPending, dialog, openDialog };
}
