import {
  ArrowDownIcon,
  ArrowsOutSimpleIcon,
  ArrowUpIcon,
  ChartLineUpIcon,
  FileTextIcon,
  XIcon,
} from "@phosphor-icons/react";
import { canCreateImplementationPr } from "@posthog/core/inbox/reportActions";
import { renderableReportChartIds } from "@posthog/core/inbox/reportCharts";
import {
  type InboxScope,
  inboxReviewerScopeValue,
  inboxScopeTriggerLabel,
} from "@posthog/core/inbox/reportMembership";
import {
  deriveHeadline,
  displayConventionalCommitTitle,
  parseConventionalCommitTitle,
  parsePrUrl,
  splitReportSummary,
} from "@posthog/core/inbox/reportPresentation";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { isDismissalReasonSnooze } from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import { ConventionalCommitScopeTag } from "@posthog/ui/features/inbox/components/ConventionalCommitScopeTag";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import {
  DismissReportDialog,
  type DismissReportDialogResult,
} from "@posthog/ui/features/inbox/components/DismissReportDialog";
import { ReportChartsSection } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { ReportChatSidebar } from "@posthog/ui/features/inbox/components/ReportChatSidebar";
import { ReportVerdictBanner } from "@posthog/ui/features/inbox/components/ReportVerdictBanner";
import { SuggestedReviewerAvatarStack } from "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack";
import { SignalReportSummaryMarkdown } from "@posthog/ui/features/inbox/components/utils/SignalReportSummaryMarkdown";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { useInboxBulkActions } from "@posthog/ui/features/inbox/hooks/useInboxBulkActions";
import { useInboxReportDetailPrefetch } from "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch";
import {
  findContinuableImplementationTask,
  getTaskPrUrl,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { KeyHint } from "@posthog/ui/primitives/KeyHint";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { navigateToInboxReportDetail } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  const sessionContextRef = useRef({
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
  const { data: reportTasks, isLoading: reportTasksLoading } = useReportTasks(
    reportId ?? "",
    report?.status ?? "candidate",
  );
  const continuableTask = findContinuableImplementationTask(reportTasks);
  const canCreatePr =
    report?.status === "ready" &&
    canCreateImplementationPr(report, {
      hasLiveImplementationTask: continuableTask !== null,
      isTaskLookupPending: reportTasksLoading,
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
  const conventionalTitle = parseConventionalCommitTitle(report?.title);
  const reportTitle = displayConventionalCommitTitle(
    report?.title,
    "Untitled report",
  );
  const headline = deriveHeadline(report?.summary);
  const sourceMeta = (report?.source_products ?? [])
    .map((sourceProduct) => getSourceProductMeta(sourceProduct))
    .find((item) => item !== null);
  const SourceIcon = sourceMeta?.Icon;
  const summarySplit = useMemo(
    () => splitReportSummary(report?.summary),
    [report?.summary],
  );
  const chartIds = renderableReportChartIds(report?.charts);
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
  );
  const dismissPending = bulkActions.isSuppressing || bulkActions.isSnoozing;

  const handleDismissConfirm = useCallback(
    async (result: DismissReportDialogResult) => {
      const ok = isDismissalReasonSnooze(result.reason)
        ? await bulkActions.snoozeSelected()
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
        <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col justify-center gap-3 px-6 py-6">
          <div className="flex items-center justify-between gap-3 px-1">
            <span className="text-[13px] text-gray-10 tabular-nums">
              {clamped + 1} of {reports.length} ·{" "}
              {inboxScopeTriggerLabel(scope)}
              {hasActiveFilters ? " · Filtered" : ""}
            </span>
            <Button
              type="button"
              variant="link-muted"
              size="sm"
              onClick={handleExit}
            >
              <XIcon />
              Exit triage
            </Button>
          </div>

          {previousReport && (
            <Button
              type="button"
              variant="outline"
              className="h-12 w-full justify-start gap-3 px-4 text-gray-9"
              onClick={goPrev}
            >
              <ArrowUpIcon />
              <span className="truncate">
                {displayConventionalCommitTitle(
                  previousReport.title,
                  "Untitled report",
                )}
              </span>
            </Button>
          )}

          <section className="overflow-hidden rounded-lg border border-border bg-(--color-panel-solid)">
            <div className="flex flex-col gap-5 p-6">
              {sourceMeta && SourceIcon && (
                <div className="flex items-center gap-2 font-medium text-[13px] text-gray-10">
                  <SourceIcon style={{ color: sourceMeta.color }} />
                  <span>{sourceMeta.label}</span>
                </div>
              )}

              <div className="flex items-center gap-5">
                <PriorityMonogram priority={report.priority} size="hero" />
                <h2 className="min-w-0 font-semibold text-[32px] text-gray-12 leading-tight tracking-tight">
                  {conventionalTitle && (
                    <ConventionalCommitScopeTag
                      type={conventionalTitle.type}
                      scope={conventionalTitle.scope}
                      size="hero"
                    />
                  )}
                  {reportTitle}
                </h2>
              </div>

              {headline && (
                <p className="text-[15px] text-gray-11 leading-relaxed">
                  {headline}
                </p>
              )}

              <div className="flex flex-wrap items-center gap-2 text-[13px] text-gray-10">
                <span className="tabular-nums">
                  {report.signal_count} signal
                  {report.signal_count === 1 ? "" : "s"}
                </span>
                <span aria-hidden>·</span>
                <span className="flex items-center gap-1">
                  First seen
                  <RelativeTimestamp
                    timestamp={report.created_at}
                    className="text-[13px]"
                  />
                </span>
                <span aria-hidden>·</span>
                <span className="flex items-center gap-1">
                  Last updated
                  <RelativeTimestamp
                    timestamp={report.updated_at ?? report.created_at}
                    className="text-[13px]"
                  />
                </span>
                <SuggestedReviewerAvatarStack
                  report={report}
                  surface="triage"
                />
              </div>

              {expanded && (
                <div className="flex flex-col gap-3 border-(--gray-5) border-t pt-5">
                  {report.charts && report.charts.length > 0 && (
                    <DetailSection Icon={ChartLineUpIcon} title="Charts">
                      <ReportChartsSection
                        reportId={report.id}
                        charts={report.charts}
                      />
                    </DetailSection>
                  )}
                  {summarySplit.sections.length === 0 ? (
                    <SignalReportSummaryMarkdown
                      content={report.summary}
                      fallback="No summary yet. The agent is still investigating."
                      variant="detail"
                      pending={report.status === "in_progress"}
                      chartIds={chartIds}
                    />
                  ) : (
                    <>
                      {summarySplit.lede && (
                        <SignalReportSummaryMarkdown
                          content={summarySplit.lede}
                          fallback=""
                          variant="detail"
                          pending={report.status === "in_progress"}
                          chartIds={chartIds}
                        />
                      )}
                      {summarySplit.sections.map((section, sectionIndex) => (
                        <DetailSection
                          key={`${report.id}-${section.title}-${sectionIndex}`}
                          Icon={FileTextIcon}
                          title={section.title}
                        >
                          <SignalReportSummaryMarkdown
                            content={section.body}
                            fallback=""
                            variant="detail"
                            pending={false}
                            chartIds={chartIds}
                          />
                        </DetailSection>
                      ))}
                    </>
                  )}
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-(--gray-5) border-t bg-(--gray-2) px-5 py-3">
              <ReportVerdictBanner
                report={report}
                variant="triage-actions"
                prHotkey={dismissOpen || !prShortcut ? undefined : "c"}
                surface="triage"
              />
              <div className="ml-auto flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 gap-2 px-4 text-[14px]"
                  onClick={handleOpenReport}
                >
                  <ArrowsOutSimpleIcon />
                  Open report
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 gap-2 px-4 text-[14px]"
                  onClick={() => setExpanded((current) => !current)}
                >
                  <FileTextIcon />
                  {expanded ? "Hide summary" : "Read summary"}
                </Button>
              </div>
            </div>
          </section>

          {nextReport && (
            <Button
              type="button"
              variant="outline"
              className="h-12 w-full justify-start gap-3 px-4 text-gray-9"
              onClick={goNext}
            >
              <ArrowDownIcon />
              <span className="truncate">
                {displayConventionalCommitTitle(
                  nextReport.title,
                  "Untitled report",
                )}
              </span>
            </Button>
          )}

          <div className="flex flex-wrap items-center justify-center gap-4 text-[13px] text-gray-10">
            <span className="flex items-center gap-1">
              <KeyHint>↑</KeyHint>
              <KeyHint>↓</KeyHint>
              move
            </span>
            {prShortcut && (
              <span className="flex items-center gap-1">
                <KeyHint>C</KeyHint>
                {prShortcut === "open" ? "open PR" : "create PR"}
              </span>
            )}
            <span className="flex items-center gap-1">
              <KeyHint>A</KeyHint>
              archive
            </span>
            <span className="flex items-center gap-1">
              <KeyHint>O</KeyHint>
              open
            </span>
            <span className="flex items-center gap-1">
              <KeyHint>Enter</KeyHint>
              summary
            </span>
            <span className="flex items-center gap-1">
              <KeyHint>Esc</KeyHint>
              exit
            </span>
          </div>
        </div>

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
      {chatOpen && <ReportChatSidebar report={report} />}
    </div>
  );
}
