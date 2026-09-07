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
import { useInboxReportActionDraftStore } from "@posthog/ui/features/inbox/stores/inboxReportActionDraftStore";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

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
  const draftGeneration = useInboxReportActionDraftStore(
    (state) => state.generation,
  );
  const retryDraft = useInboxReportActionDraftStore(
    (state) => state.resolve[report.id],
  );
  const setRetryDraft = useInboxReportActionDraftStore(
    (state) => state.setResolve,
  );
  const queryClient = useQueryClient();
  const fireAction = useReportActionTracker(report, surface, triageId);
  const trackResult = useReportActionResultTracker(report, surface, triageId);
  const inFlightRef = useRef(false);
  const startedAtRef = useRef<number | null>(null);
  const mutation = useAuthenticatedMutation<
    SignalReport,
    Error,
    ResolveReportDialogResult & { draftGeneration: number },
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
      onSuccess: (updatedReport, result) => {
        updateInboxReportCaches(queryClient, [updatedReport]);
        setRetryDraft(result.draftGeneration, report.id, undefined);
        setInitialReason(undefined);
        setInitialNote("");
        if (startedAtRef.current !== null) {
          trackResult("resolve", "succeeded", startedAtRef.current);
        }
      },
      onError: (error, result, context) => {
        if (context) {
          restoreInboxReportCaches(queryClient, context.cacheSnapshot);
        }
        const draft =
          useInboxReportActionDraftStore.getState().resolve[report.id];
        if (draft) {
          setRetryDraft(result.draftGeneration, report.id, {
            ...draft,
            reopen: true,
          });
        }
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

  useEffect(() => {
    if (!retryDraft?.reopen) return;
    setInitialReason(retryDraft.reason);
    setInitialNote(retryDraft.note);
    setOpen(true);
  }, [retryDraft]);

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
      setRetryDraft(draftGeneration, report.id, {
        reason,
        note,
        reopen: false,
      });
      setInitialReason(reason);
      setInitialNote(note);
      setOpen(false);
      void mutation.mutateAsync({ reason, note, draftGeneration }).catch(() => {
        const draft =
          useInboxReportActionDraftStore.getState().resolve[report.id];
        if (draft) {
          setRetryDraft(draftGeneration, report.id, {
            ...draft,
            reopen: true,
          });
        }
      });
    },
    [draftGeneration, fireAction, mutation, report.id, setRetryDraft],
  );
  const dialog = open ? (
    <ResolveReportDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setRetryDraft(draftGeneration, report.id, undefined);
        }
      }}
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
