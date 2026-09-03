import {
  ArrowSquareOutIcon,
  ArrowsOutSimpleIcon,
  ChatCircleIcon,
  CheckCircleIcon,
  EyeSlashIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import {
  canCreateImplementationPr,
  canResolveReport,
} from "@posthog/core/inbox/reportActions";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import {
  deriveReportVerdict,
  type ReportVerdictTone,
} from "@posthog/core/inbox/reportVerdict";
import {
  Button,
  cn,
  Field,
  FieldDescription,
  FieldLabel,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Spinner,
  Textarea,
} from "@posthog/quill";
import type { InboxReportActionSurface } from "@posthog/shared/analytics-events";
import type { SignalReport, Task } from "@posthog/shared/types";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useCreatePrReport } from "@posthog/ui/features/inbox/hooks/useCreatePrReport";
import { useDiscussReport } from "@posthog/ui/features/inbox/hooks/useDiscussReport";
import { useInboxReportDismissAction } from "@posthog/ui/features/inbox/hooks/useInboxReportDismissAction";
import { useInboxReportResolveAction } from "@posthog/ui/features/inbox/hooks/useInboxReportResolveAction";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import {
  findContinuableImplementationTask,
  findLatestDiscussionTask,
  findPendingStartedTaskId,
  getTaskPrUrl,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { openTaskInput, useOpenTask } from "@posthog/ui/router/useOpenTask";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

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

type ReportVerdictBannerVariant = "full" | "header-actions" | "triage-actions";

interface ReportVerdictBannerProps {
  report: SignalReport;
  variant?: ReportVerdictBannerVariant;
  prHotkey?: string;
  resolveHotkey?: string;
  /** Hide the full banner after the reader starts or resumes report work. */
  initialEngagementOnly?: boolean;
  /** Called after an action opens the report's conversation dock. */
  onEngaged?: () => void;
  /** Analytics and behavior context for actions rendered in this banner. */
  surface?: InboxReportActionSurface;
  triageId?: string;
}

/**
 * The report's decision bar, closing the document: what state the report is
 * in, what it asks of the reader, and every action that answers the ask -
 * start the fix, review work in flight, discuss, or dismiss.
 */
export function ReportVerdictBanner({
  report,
  variant = "full",
  prHotkey,
  resolveHotkey,
  initialEngagementOnly = false,
  onEngaged,
  surface = "detail_pane",
  triageId,
}: ReportVerdictBannerProps) {
  const compact = variant === "header-actions";
  const triageActions = variant === "triage-actions";
  const buttonClass = BIG_BUTTON;
  const { data: artefactsResp, isLoading: artefactsLoading } =
    useInboxReportArtefacts(report.id);
  const cloudRepository = extractRepoSelectionRepository(
    artefactsResp?.results,
  );

  // Structural dedupe guard: re-engaging a report that already has live
  // implementation work (an open PR, or a run still in flight) should continue
  // that task rather than spin up a duplicate PR. `report.implementation_pr_url`
  // alone is unreliable here — it can be stale or not yet set — so we also look
  // at the linked implementation task's own state.
  const {
    data: reportTasks,
    isLoading: reportTasksLoading,
    isError: reportTasksFailed,
  } = useReportTasks(report.id, report.status);
  const continuableTask = findContinuableImplementationTask(reportTasks);
  const canCreatePr = canCreateImplementationPr(report, {
    hasLiveImplementationTask: continuableTask !== null,
    // A failed lookup leaves task state unknown, same as a pending one. Reading it
    // as "no live task" would offer a second PR on work that already has one.
    isTaskLookupPending: reportTasksLoading || reportTasksFailed,
  });
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
  const externalPrUrl =
    existingPrUrl && parsePrUrl(existingPrUrl) ? existingPrUrl : null;
  const startedTaskId = useReportChatPanelStore(
    (state) => state.startedTaskIdByReport[report.id] ?? null,
  );
  const hasPriorEngagement =
    findPendingStartedTaskId(reportTasks, startedTaskId) !== null ||
    hasExistingPr ||
    findLatestDiscussionTask(reportTasks) !== null;

  const verdict = deriveReportVerdict(report, { hasExistingPr });

  const fireAction = useReportActionTracker(report, surface, triageId);
  const openTask = useOpenTask();
  const queryClient = useQueryClient();
  const [prOpen, setPrOpen] = useState(false);
  const [prFeedback, setPrFeedback] = useState("");
  const [askOpen, setAskOpen] = useState(false);
  const [askQuestion, setAskQuestion] = useState("");

  const setChatOpen = useReportChatPanelStore((s) => s.setOpen);
  const setPendingQuote = useReportChatPanelStore((s) => s.setPendingQuote);
  const rememberStartedTask = useReportChatPanelStore(
    (s) => s.rememberStartedTask,
  );
  const [engaged, setEngaged] = useState(false);
  const { generalChannel, isLoading: channelsLoading } = useTaskChannels();
  const taskChannelId = report.channel_id ?? generalChannel?.id ?? null;
  const awaitingChannel = taskChannelId === null && channelsLoading;

  const handleTaskCreated = useCallback(
    (task: Task) => {
      queryClient.setQueryData(taskDetailQuery(task.id).queryKey, task);
      rememberStartedTask(report.id, task.id);
      setAskOpen(false);
      setAskQuestion("");
      setEngaged(true);
      setChatOpen(true);
      void queryClient.invalidateQueries({
        queryKey: ["inbox", "report-tasks", report.id],
      });
      onEngaged?.();
    },
    [queryClient, rememberStartedTask, report.id, setChatOpen, onEngaged],
  );

  const { createPrReport, isCreatingPr } = useCreatePrReport({
    reportId: report.id,
    reportTitle: report.title ?? null,
    cloudRepository,
    surface,
    triageId,
    // The dock binds to the new task the moment it exists — and only then does
    // the view advance. A failed create (offline, missing repo/integration/
    // model, API error) never reaches here, so the report and its actions stay
    // put instead of opening an empty dock or, in triage, navigating away.
    onTaskCreated: handleTaskCreated,
  });
  const { discussReport, isDiscussing } = useDiscussReport({
    report,
    channelId: taskChannelId,
    redirectOnSuccess: false,
    surface,
    triageId,
    onTaskCreated: handleTaskCreated,
  });

  // Keep Dismiss beside Create PR because both resolve the review decision.
  // Offer it wherever the report is waiting on a person
  // (several verdict bodies tell the reader to archive; the button should be
  // right there). Running reports keep it out of the banner because the header's
  // Dismiss covers that rare case.
  const { dialog: dismissDialog, openDialog: openDismissDialog } =
    useInboxReportDismissAction(report, surface, triageId);
  const {
    dialog: resolveDialog,
    isPending: resolvePending,
    openDialog: openResolveDialog,
  } = useInboxReportResolveAction(report, surface, triageId);
  const canDismissHere =
    report.status === "ready" ||
    report.status === "failed" ||
    report.status === "pending_input";

  const handleCreatePr = useCallback(() => {
    const trimmed = prFeedback.trim();
    fireAction("create_pr", {
      has_feedback: trimmed.length > 0,
    });
    setPrFeedback("");
    setPrOpen(false);
    // The view advances from onTaskCreated once the task exists, not here — a
    // failed create leaves the report and its actions in place.
    void createPrReport(trimmed || undefined);
  }, [createPrReport, fireAction, prFeedback]);

  const handleComposeImplementation = useCallback(() => {
    if (!cloudRepository) return;
    openTaskInput({
      initialPrompt: "Implement the recommended next step in this report.",
      initialCloudRepository: cloudRepository,
      reportAssociation: {
        reportId: report.id,
        title: report.title ?? "Untitled report",
      },
    });
  }, [cloudRepository, report.id, report.title]);

  const handleOpenPr = useCallback(() => {
    if (!externalPrUrl) return;
    fireAction("open_pr");
    openExternalUrl(externalPrUrl);
  }, [externalPrUrl, fireAction]);

  const handleOpenTask = useCallback(() => {
    if (!continuableTask) return;
    fireAction("open_task");
    if (surface === "triage") {
      setChatOpen(true);
      onEngaged?.();
      return;
    }
    void openTask(continuableTask);
  }, [continuableTask, fireAction, onEngaged, openTask, setChatOpen, surface]);

  const handleAsk = useCallback(() => {
    if (isCreatingPr || isDiscussing || awaitingChannel || reportTasksLoading) {
      return;
    }
    const trimmed = askQuestion.trim();
    fireAction("discuss", { has_question: trimmed.length > 0 });
    if (hasPriorEngagement) {
      if (trimmed) {
        setPendingQuote(report.id, trimmed);
      }
      setAskOpen(false);
      setAskQuestion("");
      setEngaged(true);
      setChatOpen(true);
      onEngaged?.();
      return;
    }
    void discussReport(trimmed || undefined);
  }, [
    isCreatingPr,
    isDiscussing,
    awaitingChannel,
    reportTasksLoading,
    askQuestion,
    fireAction,
    hasPriorEngagement,
    report.id,
    setPendingQuote,
    setChatOpen,
    onEngaged,
    discussReport,
  ]);

  // The banner carries the report's one action: create a PR, or review the one
  // already in flight. Offer it whenever the report can start a PR (`canCreatePr`
  // already restricts that to ready-actionable and pending-input reports) or
  // already holds live implementation work.
  // Terminal reports (merged/archived) get no action; their verdict says so.
  const isTerminalReport =
    report.status === "resolved" ||
    report.status === "suppressed" ||
    report.status === "deleted";
  const showActions = !isTerminalReport;
  const shouldComposeImplementation =
    variant === "full" && !hasExistingPr && canCreatePr;

  // Keyboard actions use the same guards as their buttons so shortcuts cannot
  // bypass loading, disabled, or duplicate-work states.
  useEffect(() => {
    if (!prHotkey) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const matchesPr = event.key === prHotkey;
      if (!matchesPr) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }
      // An open dialog owns the keyboard because its buttons are not typing
      // targets and actions must not open underneath it.
      if (document.querySelector('[role="dialog"], [role="alertdialog"]')) {
        return;
      }
      if (report.status !== "ready" || isCreatingPr) return;
      if (externalPrUrl) {
        event.preventDefault();
        handleOpenPr();
      } else if (canCreatePr) {
        event.preventDefault();
        setPrOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    prHotkey,
    report.status,
    isCreatingPr,
    externalPrUrl,
    canCreatePr,
    handleOpenPr,
  ]);

  useEffect(() => {
    if (!resolveHotkey || !canResolveReport(report)) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.key !== resolveHotkey ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey
      ) {
        return;
      }
      const target = event.target;
      if (
        (target instanceof HTMLElement &&
          (target.isContentEditable ||
            ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) ||
        document.querySelector('[role="dialog"], [role="alertdialog"]')
      ) {
        return;
      }
      event.preventDefault();
      openResolveDialog();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [openResolveDialog, report, resolveHotkey]);

  if (
    initialEngagementOnly &&
    (reportTasksLoading || engaged || hasPriorEngagement)
  ) {
    return null;
  }

  const dismissButton = canDismissHere && !compact && (
    <Button
      type="button"
      variant="outline"
      onClick={() => openDismissDialog()}
      className={buttonClass}
    >
      <EyeSlashIcon size={15} />
      {triageActions ? "Dismiss" : "Dismiss…"}
    </Button>
  );

  const actionsRow = showActions ? (
    <div className="flex flex-wrap items-center gap-2.5">
      {triageActions && canResolveReport(report) && (
        <Button
          type="button"
          variant="outline"
          onClick={() => openResolveDialog()}
          loading={resolvePending}
          disabled={resolvePending}
          className={buttonClass}
          data-attr="inbox-triage-resolve"
        >
          <CheckCircleIcon size={15} />
          Resolve
        </Button>
      )}
      {triageActions && dismissButton}
      {shouldComposeImplementation ? (
        <Button
          type="button"
          variant="primary"
          onClick={handleComposeImplementation}
          loading={artefactsLoading}
          disabled={artefactsLoading || !cloudRepository}
          className={buttonClass}
          data-attr="inbox-report-implement"
        >
          <GitPullRequestIcon size={15} />
          Implement
        </Button>
      ) : report.status === "ready" && externalPrUrl ? (
        <Button
          type="button"
          variant="primary"
          onClick={handleOpenPr}
          className={buttonClass}
        >
          <ArrowSquareOutIcon size={16} />
          View PR on GitHub
        </Button>
      ) : report.status === "ready" && continuableTask ? (
        <Button
          type="button"
          variant="primary"
          onClick={handleOpenTask}
          className={buttonClass}
          data-attr="inbox-report-view-task"
        >
          <ArrowsOutSimpleIcon />
          {surface === "triage" ? "Continue in chat" : "View task"}
        </Button>
      ) : report.status === "ready" && !hasExistingPr && canCreatePr ? (
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
                disabled={isCreatingPr || isDiscussing}
                className={buttonClass}
              >
                {isCreatingPr ? <Spinner /> : <GitPullRequestIcon size={15} />}
                Create PR
              </Button>
            }
          />
          <PopoverContent
            align="start"
            side="bottom"
            sideOffset={6}
            className="flex w-[420px] flex-col gap-2 p-3"
          >
            <Field>
              <FieldLabel
                className="sr-only"
                htmlFor={`report-fix-direction-${report.id}`}
              >
                Optional direction for the agent
              </FieldLabel>
              <Textarea
                id={`report-fix-direction-${report.id}`}
                autoFocus
                placeholder="Add direction for the agent (optional)…"
                rows={4}
                value={prFeedback}
                onChange={(event) => setPrFeedback(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    (event.metaKey || event.ctrlKey)
                  ) {
                    event.preventDefault();
                    handleCreatePr();
                  }
                }}
              />
            </Field>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12px] text-gray-10">
                {isMac ? "⌘↵" : "Ctrl+↵"} to start
              </span>
              <Button
                type="button"
                variant="primary"
                size="sm"
                loading={isCreatingPr}
                disabled={isCreatingPr || isDiscussing}
                onClick={handleCreatePr}
              >
                Create PR
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      ) : null}
      {!triageActions && (
        <Popover
          open={askOpen}
          onOpenChange={(next) => {
            setAskOpen(next);
            if (!next && !isDiscussing) setAskQuestion("");
          }}
        >
          <PopoverTrigger
            render={
              <Button
                type="button"
                variant="outline"
                disabled={
                  isCreatingPr ||
                  isDiscussing ||
                  awaitingChannel ||
                  reportTasksLoading
                }
                className={buttonClass}
              >
                <ChatCircleIcon size={16} />
                Ask about it
              </Button>
            }
          />
          <PopoverContent
            align="start"
            side="bottom"
            sideOffset={6}
            className="flex w-[420px] flex-col gap-2 p-3"
          >
            <Field>
              <FieldLabel
                className="sr-only"
                htmlFor={`report-question-${report.id}`}
              >
                Optional question for the agent
              </FieldLabel>
              <Textarea
                id={`report-question-${report.id}`}
                autoFocus
                placeholder="Ask a question or add direction (optional)…"
                rows={4}
                value={askQuestion}
                onChange={(event) => setAskQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    (event.metaKey || event.ctrlKey)
                  ) {
                    event.preventDefault();
                    handleAsk();
                  }
                }}
              />
              <FieldDescription>
                The full report and its evidence are included.
              </FieldDescription>
            </Field>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12px] text-gray-10">
                {isMac ? "⌘↵" : "Ctrl+↵"} to start
              </span>
              <Button
                type="button"
                variant="primary"
                size="sm"
                loading={isDiscussing}
                disabled={
                  isCreatingPr ||
                  isDiscussing ||
                  awaitingChannel ||
                  reportTasksLoading
                }
                onClick={handleAsk}
              >
                Start chat
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      )}
      {!triageActions && dismissButton}
    </div>
  ) : null;

  if (variant === "header-actions") {
    if (!actionsRow) return null;
    return actionsRow;
  }

  if (variant === "triage-actions") {
    return (
      <>
        {actionsRow}
        {resolveDialog}
        {dismissDialog}
      </>
    );
  }

  return (
    <div
      className={cn(
        "flex select-none flex-col gap-3 rounded-lg border p-4",
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
