import {
  ArrowsOutSimpleIcon,
  CaretLeftIcon,
  CaretRightIcon,
  ChartLineUpIcon,
  FileTextIcon,
  XIcon,
} from "@phosphor-icons/react";
import { renderableReportChartIds } from "@posthog/core/inbox/reportCharts";
import {
  type InboxScope,
  inboxReviewerScopeValue,
  inboxScopeTriggerLabel,
} from "@posthog/core/inbox/reportMembership";
import {
  humanizeReportTitle,
  splitReportSummary,
} from "@posthog/core/inbox/reportPresentation";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { isDismissalReasonSnooze } from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import {
  DismissReportDialog,
  type DismissReportDialogResult,
} from "@posthog/ui/features/inbox/components/DismissReportDialog";
import { ReportChartsSection } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import { ReportChatSidebar } from "@posthog/ui/features/inbox/components/ReportChatSidebar";
import { ReportVerdictBanner } from "@posthog/ui/features/inbox/components/ReportVerdictBanner";
import { SuggestedReviewerAvatarStack } from "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack";
import { SignalReportPriorityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge";
import { SignalReportSummaryMarkdown } from "@posthog/ui/features/inbox/components/utils/SignalReportSummaryMarkdown";
import { useInboxBulkActions } from "@posthog/ui/features/inbox/hooks/useInboxBulkActions";
import { useInboxReportDetailPrefetch } from "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { navigateToInboxReportDetail } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const isMac =
  typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

/** A keyboard hint chip; quill has no kbd primitive, so plain HTML carries it. */
function KeyCap({ children }: { children: string }) {
  return (
    <kbd className="rounded border border-(--gray-6) bg-(--gray-2) px-1 font-mono text-[11.5px] text-gray-11">
      {children}
    </kbd>
  );
}

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
 * One report at a time, keyboard-driven: the fast way through a pile of
 * decisions. Walks the needs-a-decision queue in the list's order — j/k (or
 * arrows) move, e opens archive, enter expands in place, esc leaves.
 * Archiving auto-advances: the archived report drops out of the queue and the
 * next one takes its place under the same index.
 */
export function ReportTriageFocus({
  reports,
  allReports,
  scope,
  hasActiveFilters,
  onExit,
}: {
  /** The decision queue, in the list's current sort order. */
  reports: SignalReport[];
  /** Superset backing archive eligibility (mirrors the list shells). */
  allReports: SignalReport[];
  /** Scope and filter context inherited from the list that opened triage. */
  scope: InboxScope;
  hasActiveFilters: boolean;
  onExit: () => void;
}) {
  const [index, setIndex] = useState(0);
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

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      // The dialog owns the keyboard while open; typing surfaces always do.
      if (dismissOpen || isTypingTarget(event.target)) return;
      const enterAction = triageEnterAction(event);
      if (enterAction === "open") {
        event.preventDefault();
        if (report) {
          handleExit();
          navigateToInboxReportDetail(report.id);
        }
        return;
      }
      if (enterAction === "toggle") {
        event.preventDefault();
        if (report) setExpanded((current) => !current);
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      switch (event.key) {
        case "k":
        case "ArrowDown":
        case "ArrowRight":
          event.preventDefault();
          goNext();
          break;
        case "j":
        case "ArrowUp":
        case "ArrowLeft":
          event.preventDefault();
          goPrev();
          break;
        case "e":
          event.preventDefault();
          if (report) setDismissOpen(true);
          break;
        case "Escape":
          event.preventDefault();
          handleExit();
          break;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [dismissOpen, report, goNext, goPrev, handleExit]);

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
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-6 py-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                aria-label="Previous report"
                disabled={clamped === 0}
                onClick={goPrev}
              >
                <CaretLeftIcon size={14} />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                aria-label="Next report"
                disabled={clamped >= reports.length - 1}
                onClick={goNext}
              >
                <CaretRightIcon size={14} />
              </Button>
              <span className="text-[13px] text-gray-10 tabular-nums">
                {clamped + 1} of {reports.length} ·{" "}
                {inboxScopeTriggerLabel(scope)}
                {hasActiveFilters ? " · Filtered" : ""}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setExpanded((current) => !current)}
                className="gap-1"
              >
                <ArrowsOutSimpleIcon size={12} />
                {expanded ? "Collapse report" : "Show report"}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleExit}
                className="gap-1"
              >
                <XIcon size={12} />
                Exit triage
              </Button>
            </div>
          </div>

          <div className="flex flex-col gap-3 rounded-lg border border-border bg-(--color-panel-solid) p-5">
            <div className="flex flex-col gap-1.5">
              <h2 className="font-semibold text-[17px] text-gray-12 leading-snug">
                {humanizeReportTitle(report.title, "Untitled report")}
              </h2>
              <div className="flex items-center gap-2 text-[13px] text-gray-10">
                <SignalReportPriorityBadge priority={report.priority} />
                <span className="tabular-nums">
                  {report.signal_count} signal
                  {report.signal_count === 1 ? "" : "s"}
                </span>
                <RelativeTimestamp
                  timestamp={report.updated_at ?? report.created_at}
                  className="text-[13px]"
                />
                <SuggestedReviewerAvatarStack
                  report={report}
                  surface="triage"
                />
              </div>
            </div>

            {/* The proof stays sorted and folded — the same labeled slots as
              the detail page. The lede (the summary's own tl;dr) shows since
              it's triage-sized; each section opens on demand. Triage reads
              the verdict; research opens the full report. */}
            {report.charts && report.charts.length > 0 && (
              <DetailSection Icon={ChartLineUpIcon} title="Charts">
                <ReportChartsSection
                  reportId={report.id}
                  charts={report.charts}
                />
              </DetailSection>
            )}
            {summarySplit.sections.length === 0 ? (
              <DetailSection
                key={`${report.id}-${expanded}`}
                Icon={FileTextIcon}
                title="How we know"
                collapsible
                defaultCollapsed={!expanded}
              >
                <SignalReportSummaryMarkdown
                  content={report.summary}
                  fallback="No summary yet. The agent is still investigating."
                  variant="detail"
                  pending={report.status === "in_progress"}
                  chartIds={chartIds}
                />
              </DetailSection>
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
                    key={`${report.id}-${expanded}-${section.title}-${sectionIndex}`}
                    Icon={FileTextIcon}
                    title={section.title}
                    collapsible
                    defaultCollapsed={!expanded}
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

            {/* The decision closes the card: read first, then accept. */}
            <ReportVerdictBanner
              report={report}
              actionHotkey={dismissOpen ? undefined : "f"}
              askHotkey={dismissOpen ? undefined : "a"}
              surface="triage"
            />
          </div>

          <div className="flex items-center justify-center gap-4 text-[13px] text-gray-10">
            <span className="flex items-center gap-1">
              <KeyCap>j</KeyCap>
              <KeyCap>k</KeyCap> move
            </span>
            <span className="flex items-center gap-1">
              <KeyCap>f</KeyCap> fix
            </span>
            <span className="flex items-center gap-1">
              <KeyCap>a</KeyCap> ask
            </span>
            <span className="flex items-center gap-1">
              <KeyCap>e</KeyCap> archive
            </span>
            <span className="flex items-center gap-1">
              <KeyCap>↵</KeyCap> show
            </span>
            <span className="flex items-center gap-1">
              <KeyCap>{isMac ? "⌘↵" : "Ctrl+↵"}</KeyCap> open
            </span>
            <span className="flex items-center gap-1">
              <KeyCap>esc</KeyCap> exit
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
