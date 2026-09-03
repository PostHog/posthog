import { buildResolveRequest } from "@posthog/core/inbox/bulkActions";
import {
  type InboxReportCacheSnapshot,
  restoreInboxReportCaches,
  updateInboxReportCaches,
} from "@posthog/core/inbox/inboxQuery";
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
  const [initialNote, setInitialNote] = useState("");
  const queryClient = useQueryClient();
  const fireAction = useReportActionTracker(report, surface, triageId);
  const trackResult = useReportActionResultTracker(report, surface, triageId);
  const inFlightRef = useRef(false);
  const startedAtRef = useRef<number | null>(null);
  const mutation = useAuthenticatedMutation<
    SignalReport,
    Error,
    ResolveReportDialogResult,
    { cacheSnapshot: InboxReportCacheSnapshot }
  >(
    (client, result: ResolveReportDialogResult) =>
      client.updateSignalReportState(
        report.id,
        buildResolveRequest(result.reason, result.note),
      ),
    {
      onMutate: async (result) => {
        await queryClient.cancelQueries({
          queryKey: reportKeys.all,
          exact: false,
        });
        const optimisticReport: SignalReport = {
          ...report,
          status: "resolved",
          dismissal_reason: result.reason,
          dismissal_note: result.note || null,
        };
        return {
          cacheSnapshot: updateInboxReportCaches(
            queryClient,
            [optimisticReport],
            [report],
          ),
        };
      },
      onSuccess: (updatedReport) => {
        updateInboxReportCaches(queryClient, [updatedReport]);
        setInitialReason(undefined);
        setInitialNote("");
        if (startedAtRef.current !== null) {
          trackResult("resolve", "succeeded", startedAtRef.current);
        }
      },
      onError: (error, _result, context) => {
        if (context) {
          restoreInboxReportCaches(queryClient, context.cacheSnapshot);
        }
        setOpen(true);
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
        void queryClient.invalidateQueries({
          queryKey: reportKeys.all,
          exact: false,
        });
        void queryClient.invalidateQueries({
          queryKey: taskFeedResultsQueryRoot,
          exact: false,
        });
      },
    },
  );

  const openDialog = useCallback((reason?: ResolveReasonOptionValue) => {
    setInitialReason(reason);
    setInitialNote("");
    setOpen(true);
  }, []);
  const resolveWithReason = useCallback(
    (reason: ResolveReasonOptionValue, note = "") => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      startedAtRef.current = Date.now();
      fireAction("resolve", { dismissal_reason: reason });
      setInitialReason(reason);
      setInitialNote(note);
      setOpen(false);
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
      initialNote={initialNote}
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
