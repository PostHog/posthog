import { canCreateImplementationPr } from "@posthog/core/inbox/reportActions";
import {
  type InboxScope,
  inboxReviewerScopeValue,
  inboxScopeTriggerLabel,
} from "@posthog/core/inbox/reportMembership";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { isDismissalReasonSnooze } from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import {
  DismissReportDialog,
  type DismissReportDialogResult,
} from "@posthog/ui/features/inbox/components/DismissReportDialog";
import { ReportChatSidebar } from "@posthog/ui/features/inbox/components/ReportChatSidebar";
import { ReportTriageFocusView } from "@posthog/ui/features/inbox/components/ReportTriageFocusView";
import { ReportVerdictBanner } from "@posthog/ui/features/inbox/components/ReportVerdictBanner";
import { SuggestedReviewerAvatarStack } from "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack";
import { useInboxBulkActions } from "@posthog/ui/features/inbox/hooks/useInboxBulkActions";
import { useInboxReportDetailPrefetch } from "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch";
import {
  findContinuableImplementationTask,
  getTaskPrUrl,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { navigateToInboxReportDetail } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useEffect, useRef, useState } from "react";

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  );
}

/**
 * A focused button or link owns Enter/Space activation. The global Enter
 * shortcut must yield to it, or Tab-then-Enter on any control in the card
 * (Next, Exit, a section toggle, a verdict button) exits triage instead of
 * doing what the control says.
 */
export function isInteractiveTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    target.closest("button, a[href], [role='button']") !== null
  );
}

export function triageEnterAction(input: {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  target: EventTarget | null;
}): "toggle" | "open" | null {
  if (
    input.key !== "Enter" ||
    input.altKey ||
    isInteractiveTarget(input.target)
  ) {
    return null;
  }
  return input.metaKey || input.ctrlKey ? "open" : "toggle";
}

/**
 * Archiving auto-advances because the archived report drops out of the queue
 * and the next report takes its place under the same index.
 */
export function ReportTriageFocus({
  reports,
  allReports,
  scope,
  hasActiveFilters,
  initialReportId,
  onExit,
}: {
  /** The decision queue, in the list's current sort order. */
  reports: SignalReport[];
  /** Superset backing archive eligibility (mirrors the list shells). */
  allReports: SignalReport[];
  /** Scope and filter context inherited from the list that opened triage. */
  scope: InboxScope;
  hasActiveFilters: boolean;
  initialReportId?: string;
  onExit: () => void;
}) {
  const [index, setIndex] = useState(() => {
    const initialIndex = initialReportId
      ? reports.findIndex((report) => report.id === initialReportId)
      : -1;
    return Math.max(0, initialIndex);
  });
  const [dismissOpen, setDismissOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const chatOpen = useReportChatPanelStore((state) => state.open);
  const setChatOpen = useReportChatPanelStore((state) => state.setOpen);
  const triageIdRef = useRef(crypto.randomUUID());
  const sessionContextRef = useRef({
    triage_id: triageIdRef.current,
    queue_size: reports.length,
    scope: inboxReviewerScopeValue(scope),
    has_active_filters: hasActiveFilters,
  });
  const sessionStartedAtRef = useRef(Date.now());
  const reviewedReportIdsRef = useRef(new Set<string>());
  const sessionEndedRef = useRef(false);

  const finishSession = useCallback((endReason: "completed" | "exited") => {
    if (sessionEndedRef.current) return;
    sessionEndedRef.current = true;
    track(ANALYTICS_EVENTS.INBOX_TRIAGE_ENDED, {
      ...sessionContextRef.current,
      reports_reviewed: reviewedReportIdsRef.current.size,
      duration_ms: Date.now() - sessionStartedAtRef.current,
      end_reason: endReason,
    });
  }, []);

  useEffect(() => {
    track(ANALYTICS_EVENTS.INBOX_TRIAGE_STARTED, sessionContextRef.current);
    return () => finishSession("exited");
  }, [finishSession]);

  // The queue shrinks under us when a report is archived; clamping (rather
  // than resetting) is what makes archive-and-advance work.
  const clamped = Math.min(index, Math.max(0, reports.length - 1));
  const report = reports[clamped];
  const reportId = report?.id;
  const {
    data: reportTasks,
    isLoading: reportTasksLoading,
    isError: reportTasksFailed,
  } = useReportTasks(reportId ?? "", report?.status ?? "candidate");
  const continuableTask = findContinuableImplementationTask(reportTasks);
  const canCreatePr =
    report?.status === "ready" &&
    canCreateImplementationPr(report, {
      hasLiveImplementationTask: continuableTask !== null,
      // A failed lookup leaves task state unknown, same as a pending one.
      isTaskLookupPending: reportTasksLoading || reportTasksFailed,
    });
  const livePrUrl = report?.implementation_pr_merged
    ? null
    : report?.implementation_pr_url;
  const existingPrUrl =
    livePrUrl ?? (continuableTask ? getTaskPrUrl(continuableTask) : null);
  const canOpenPr =
    report?.status === "ready" &&
    !!existingPrUrl &&
    parsePrUrl(existingPrUrl) !== null;
  const prShortcut = canOpenPr ? "open" : canCreatePr ? "create" : null;
  const previousReport = clamped > 0 ? reports[clamped - 1] : null;
  const nextReport = clamped < reports.length - 1 ? reports[clamped + 1] : null;
  const { prefetch } = useInboxReportDetailPrefetch(
    report
      ? {
          to: "/inbox/reports/$reportId",
          params: { reportId: report.id },
        }
      : null,
  );

  useEffect(() => {
    if (!reportId) {
      setChatOpen(false);
      finishSession("completed");
      return;
    }
    reviewedReportIdsRef.current.add(reportId);
    setExpanded(false);
    setChatOpen(false);
  }, [finishSession, reportId, setChatOpen]);

  // Triage is intentionally sequential, so the next destination is known as
  // soon as the card renders. Warm it before Enter/Review is pressed instead
  // of making the detail route begin its work after navigation.
  useEffect(() => {
    prefetch();
  }, [prefetch]);

  const bulkActions = useInboxBulkActions(
    allReports,
    report?.id ?? null,
    "triage",
    triageIdRef.current,
  );
  const dismissPending = bulkActions.isSuppressing || bulkActions.isSnoozing;

  const handleDismissConfirm = useCallback(
    async (result: DismissReportDialogResult) => {
      const ok = isDismissalReasonSnooze(result.reason)
        ? await bulkActions.snoozeSelected(result)
        : await bulkActions.suppressSelected(result);
      if (ok) setDismissOpen(false);
    },
    [bulkActions],
  );

  const goNext = useCallback(
    () => setIndex((i) => Math.min(i + 1, reports.length - 1)),
    [reports.length],
  );
  const goPrev = useCallback(() => setIndex((i) => Math.max(i - 1, 0)), []);
  const handleExit = useCallback(() => {
    finishSession("exited");
    onExit();
  }, [finishSession, onExit]);
  const handleOpenReport = useCallback(() => {
    if (!report) return;
    finishSession("exited");
    navigateToInboxReportDetail(report.id, { returnToTriage: true });
  }, [finishSession, report]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        dismissOpen ||
        isTypingTarget(event.target) ||
        document.querySelector('[role="dialog"], [role="alertdialog"]')
      ) {
        return;
      }
      const enterAction = triageEnterAction(event);
      if (enterAction === "open") {
        event.preventDefault();
        handleOpenReport();
        return;
      }
      if (enterAction === "toggle") {
        event.preventDefault();
        if (report) setExpanded((current) => !current);
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          goNext();
          break;
        case "ArrowUp":
          event.preventDefault();
          goPrev();
          break;
        case "a":
          event.preventDefault();
          if (report) setDismissOpen(true);
          break;
        case "o":
          event.preventDefault();
          handleOpenReport();
          break;
        case "Escape":
          event.preventDefault();
          handleExit();
          break;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [dismissOpen, report, goNext, goPrev, handleExit, handleOpenReport]);

  if (!report) {
    // The queue ran dry mid-session — every decision is made.
    return (
      <div className="flex flex-col items-center gap-3 py-16">
        <span className="font-medium text-[15px] text-gray-12">
          All decisions made
        </span>
        <span className="text-[14px] text-gray-11">
          Nothing left in the queue.
        </span>
        <Button type="button" variant="outline" size="sm" onClick={handleExit}>
          Back to the list
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-y-auto">
        <ReportTriageFocusView
          report={report}
          position={clamped + 1}
          total={reports.length}
          scopeLabel={inboxScopeTriggerLabel(scope)}
          hasActiveFilters={hasActiveFilters}
          previousReport={previousReport}
          nextReport={nextReport}
          expanded={expanded}
          prShortcut={prShortcut}
          actions={
            <ReportVerdictBanner
              report={report}
              variant="triage-actions"
              prHotkey={dismissOpen || !prShortcut ? undefined : "c"}
              resolveHotkey={dismissOpen ? undefined : "r"}
              surface="triage"
              triageId={triageIdRef.current}
            />
          }
          reviewers={
            <SuggestedReviewerAvatarStack
              report={report}
              surface="triage"
              triageId={triageIdRef.current}
            />
          }
          onExit={handleExit}
          onPrevious={goPrev}
          onNext={goNext}
          onOpenReport={handleOpenReport}
          onToggleSummary={() => setExpanded((current) => !current)}
        />

        {dismissOpen && (
          <DismissReportDialog
            open
            onOpenChange={setDismissOpen}
            report={report}
            isSubmitting={dismissPending}
            snoozeDisabledReason={bulkActions.snoozeDisabledReason}
            onConfirm={handleDismissConfirm}
          />
        )}
      </div>
      {chatOpen && (
        <ReportChatSidebar
          report={report}
          surface="triage"
          triageId={triageIdRef.current}
        />
      )}
    </div>
  );
}
