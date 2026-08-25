import {
  ArchiveIcon,
  ArrowSquareOutIcon,
  ClockIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import { canCreateImplementationPr } from "@posthog/core/inbox/reportActions";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import {
  deriveReportVerdict,
  type ReportVerdictTone,
} from "@posthog/core/inbox/reportVerdict";
import {
  Button,
  cn,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Spinner,
  Textarea,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { useCreatePrReport } from "@posthog/ui/features/inbox/hooks/useCreatePrReport";
import { useInboxBulkActions } from "@posthog/ui/features/inbox/hooks/useInboxBulkActions";
import { useInboxReportDismissAction } from "@posthog/ui/features/inbox/hooks/useInboxReportDismissAction";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import {
  findContinuableImplementationTask,
  getTaskPrUrl,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useCallback, useEffect, useMemo, useState } from "react";

const isMac =
  typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

// Same sizing as PrDecisionBlock: the decision is the page's one ask.
const BIG_BUTTON = "h-9 gap-2 px-4 text-[14px]";

const TONE_CLASS: Record<ReportVerdictTone, string> = {
  decision: "border-(--amber-6) bg-(--amber-2)",
  danger: "border-(--red-6) bg-(--red-2)",
  progress: "border-(--gray-5) bg-(--gray-1)",
  info: "border-(--gray-5) bg-(--gray-1)",
};

type ReportVerdictBannerVariant = "full" | "header-actions";

interface ReportVerdictBannerProps {
  report: SignalReport;
  /**
   * full: status box + action row (the triage card). header-actions: the
   * compact action row alone (the detail page's sticky top bar owns the
   * verbs, and the page shows no status box).
   */
  variant?: ReportVerdictBannerVariant;
  /** Key that fires the primary action (triage mode passes "f"). */
  actionHotkey?: string;
  /**
   * Called after an action opens the report's conversation dock. Surfaces
   * without a dock (the triage card) navigate to the report here.
   */
  onEngaged?: () => void;
}

/**
 * The report's decision bar, closing the document: what state the report is
 * in, what it asks of the reader, and every action that answers the ask -
 * start the fix (or continue the one in flight), defer, or archive.
 */
export function ReportVerdictBanner({
  report,
  variant = "full",
  actionHotkey,
  onEngaged,
}: ReportVerdictBannerProps) {
  const compact = variant === "header-actions";
  const buttonClass = BIG_BUTTON;
  const canCreatePr = canCreateImplementationPr(report);
  const { data: artefactsResp } = useInboxReportArtefacts(report.id);
  const cloudRepository = extractRepoSelectionRepository(
    artefactsResp?.results,
  );

  // Structural dedupe guard: re-engaging a report that already has live
  // implementation work (an open PR, or a run still in flight) should continue
  // that task rather than spin up a duplicate PR. `report.implementation_pr_url`
  // alone is unreliable here — it can be stale or not yet set — so we also look
  // at the linked implementation task's own state.
  const { data: reportTasks, isLoading: reportTasksLoading } = useReportTasks(
    report.id,
    report.status,
  );
  const continuableTask = findContinuableImplementationTask(reportTasks);
  // A merged PR is history, not live work: the report only still exists
  // because evidence kept arriving after the fix, so it reads by its own
  // state (usually "needs your decision" again) rather than "review the PR".
  const livePrUrl = report.implementation_pr_merged
    ? null
    : report.implementation_pr_url;
  // The merged PR is history, not live work, but history the reader needs
  // visible: it explains why an already-fixed issue is asking for a decision.
  const mergedPr =
    report.implementation_pr_merged && report.implementation_pr_url
      ? parsePrUrl(report.implementation_pr_url)
      : null;
  const existingPrUrl =
    livePrUrl ?? (continuableTask ? getTaskPrUrl(continuableTask) : null);
  const hasExistingPr = !!existingPrUrl || !!continuableTask;

  const verdict = deriveReportVerdict(report, { hasExistingPr });

  const fireAction = useReportActionTracker(report);

  const setChatOpen = useReportChatPanelStore((s) => s.setOpen);
  const rememberStartedTask = useReportChatPanelStore(
    (s) => s.rememberStartedTask,
  );

  const { createPrReport, isCreatingPr } = useCreatePrReport({
    reportId: report.id,
    reportTitle: report.title ?? null,
    cloudRepository,
    // The dock binds to the new task the moment it exists — and only then does
    // the view advance. A failed create (offline, missing repo/integration/
    // model, API error) never reaches here, so the report and its actions stay
    // put instead of opening an empty dock or, in triage, navigating away.
    onTaskCreated: (task) => {
      rememberStartedTask(report.id, task.id);
      setChatOpen(true);
      onEngaged?.();
    },
  });

  const [prOpen, setPrOpen] = useState(false);
  const [prFeedback, setPrFeedback] = useState("");

  // Archive is the "no" beside Fix & monitor's "yes" — a decision, so it lives in
  // the decision row. Offered wherever the report is waiting on a person
  // (several verdict bodies tell the reader to archive; the button should be
  // right there). Running reports keep it out of the banner — the header's
  // Dismiss covers that rare case.
  const { dialog: dismissDialog, openDialog: openDismissDialog } =
    useInboxReportDismissAction(report);
  // Defer = snooze: the report re-promotes itself when enough new evidence
  // lands. Same mechanism the triage card's d key uses.
  const reportsForBulk = useMemo(() => [report], [report]);
  const bulkActions = useInboxBulkActions(
    reportsForBulk,
    report.id,
    "detail_pane",
  );
  const canArchiveHere =
    report.status === "ready" ||
    report.status === "failed" ||
    report.status === "pending_input";

  const handleCreatePr = useCallback(() => {
    const trimmed = prFeedback.trim();
    fireAction("create_pr", {
      has_feedback: trimmed.length > 0,
      ...(trimmed ? { feedback_text: trimmed.slice(0, 500) } : {}),
    });
    setPrFeedback("");
    setPrOpen(false);
    // The view advances from onTaskCreated once the task exists, not here — a
    // failed create leaves the report and its actions in place.
    void createPrReport(trimmed || undefined);
  }, [createPrReport, fireAction, prFeedback]);

  const handleContinuePr = useCallback(() => {
    if (!continuableTask) return;
    fireAction("open_pr");
    // The conversation opens docked beside the report — the full task page
    // stays one click away in the dock header.
    setChatOpen(true);
    onEngaged?.();
  }, [continuableTask, fireAction, setChatOpen, onEngaged]);

  // The banner carries the report's one action: create the PR, or continue the
  // one in flight. Offer it whenever the report can start a PR (`canCreatePr`
  // already restricts that to ready-actionable and pending-input reports) or
  // already holds live implementation work — matching the old decision block.
  // Terminal reports (merged/archived) get no action; their verdict says so.
  const isTerminalReport =
    report.status === "resolved" ||
    report.status === "suppressed" ||
    report.status === "deleted";
  const showActions = !isTerminalReport && (canCreatePr || hasExistingPr);

  // One key fires the primary action (triage mode passes "f"): continue the
  // task when a PR exists, otherwise start the fix with no extra direction.
  useEffect(() => {
    if (!actionHotkey) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== actionHotkey) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }
      // An open dialog owns the keyboard: its buttons aren't typing targets,
      // but f must not start a PR underneath the archive dialog.
      if (document.querySelector('[role="dialog"], [role="alertdialog"]')) {
        return;
      }
      event.preventDefault();
      if (report.status !== "ready" || isCreatingPr) return;
      if (hasExistingPr) {
        if (continuableTask) handleContinuePr();
      } else if (canCreatePr) {
        handleCreatePr();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    actionHotkey,
    report.status,
    isCreatingPr,
    hasExistingPr,
    continuableTask,
    canCreatePr,
    handleContinuePr,
    handleCreatePr,
  ]);

  const actionsRow = showActions ? (
    <div className="flex flex-wrap items-center gap-2.5">
      {report.status === "ready" && hasExistingPr ? (
        <>
          <Button
            type="button"
            variant="primary"
            disabled={isCreatingPr || !continuableTask}
            onClick={handleContinuePr}
            className={buttonClass}
          >
            {reportTasksLoading && !continuableTask ? (
              <Spinner />
            ) : (
              <GitPullRequestIcon size={15} />
            )}
            Continue the task
          </Button>
          {existingPrUrl && !compact && (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                if (existingPrUrl) openExternalUrl(existingPrUrl);
              }}
              className={buttonClass}
            >
              <ArrowSquareOutIcon size={16} />
              View PR on GitHub
            </Button>
          )}
        </>
      ) : report.status === "ready" && canCreatePr ? (
        <Popover
          open={prOpen}
          onOpenChange={(next) => {
            setPrOpen(next);
            if (!next) setPrFeedback("");
          }}
        >
          <PopoverTrigger
            render={
              <Button
                type="button"
                variant="primary"
                disabled={isCreatingPr}
                className={buttonClass}
              >
                {isCreatingPr ? <Spinner /> : <GitPullRequestIcon size={15} />}
                Fix & monitor
              </Button>
            }
          />
          <PopoverContent
            align="start"
            side="bottom"
            sideOffset={6}
            className="flex w-[420px] flex-col gap-2 p-3"
          >
            <Textarea
              aria-label="Optional direction for the agent"
              autoFocus
              placeholder="Add direction for the agent (optional)…"
              rows={4}
              value={prFeedback}
              onChange={(event) => setPrFeedback(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  handleCreatePr();
                }
              }}
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12px] text-gray-10">
                {isMac ? "⌘↵" : "Ctrl+↵"} to start
              </span>
              <Button
                type="button"
                variant="primary"
                size="sm"
                disabled={isCreatingPr}
                onClick={handleCreatePr}
              >
                Fix & monitor
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      ) : null}
      {canArchiveHere && !compact && (
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                variant="outline"
                disabled={
                  bulkActions.snoozeDisabledReason !== null ||
                  bulkActions.isSnoozing
                }
                onClick={() => void bulkActions.snoozeSelected()}
                className={buttonClass}
              >
                {bulkActions.isSnoozing ? <Spinner /> : <ClockIcon size={16} />}
                Defer
              </Button>
            }
          />
          <TooltipContent side="bottom">
            {bulkActions.snoozeDisabledReason ??
              "Snooze until enough new evidence arrives"}
          </TooltipContent>
        </Tooltip>
      )}
      {canArchiveHere && !compact && (
        <Button
          type="button"
          variant="outline"
          onClick={openDismissDialog}
          className={buttonClass}
        >
          <ArchiveIcon size={15} />
          Archive…
        </Button>
      )}
    </div>
  ) : null;

  if (variant === "header-actions") {
    if (!actionsRow) return null;
    return actionsRow;
  }

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-lg border p-4",
        TONE_CLASS[verdict.tone],
      )}
    >
      <div className="flex flex-col gap-1">
        <span className="flex items-center gap-2 font-semibold text-[15px] text-gray-12">
          {verdict.tone === "progress" && <Spinner />}
          {verdict.title}
        </span>
        <span className="text-[14px] text-gray-11">{verdict.body}</span>
        {mergedPr && report.implementation_pr_url && (
          <a
            href={report.implementation_pr_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[13px] text-gray-10 hover:underline"
          >
            <GitPullRequestIcon size={12} />
            An earlier fix (#{mergedPr.number}) merged, but evidence kept
            arriving afterwards
          </a>
        )}
      </div>

      {actionsRow}
      {dismissDialog}
    </div>
  );
}
