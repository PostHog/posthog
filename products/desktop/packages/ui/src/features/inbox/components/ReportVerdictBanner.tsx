import { ArrowSquareOutIcon, GitPullRequestIcon } from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import { canCreateImplementationPr } from "@posthog/core/inbox/reportActions";
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
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { useCreatePrReport } from "@posthog/ui/features/inbox/hooks/useCreatePrReport";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import {
  findContinuableImplementationTask,
  getTaskPrUrl,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useOpenTask } from "@posthog/ui/router/useOpenTask";
import { useCallback, useState } from "react";

const isMac =
  typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

// Same sizing as PrDecisionBlock: the decision is the page's one ask.
const BIG_BUTTON = "h-9 gap-2 px-4 text-[13px]";

const TONE_CLASS: Record<ReportVerdictTone, string> = {
  decision: "border-(--amber-6) bg-(--amber-2)",
  danger: "border-(--red-6) bg-(--red-2)",
  progress: "border-(--gray-5) bg-(--gray-1)",
  info: "border-(--gray-5) bg-(--gray-1)",
};

interface ReportVerdictBannerProps {
  report: SignalReport;
}

/**
 * The report's verdict, stated before the prose: what state it is in, what it
 * asks of the reader, and the action that answers the ask (start the PR, or
 * continue the one in flight). Replaces the old decision block that sat below
 * the summary, where the ask arrived only after the wall of text.
 */
export function ReportVerdictBanner({ report }: ReportVerdictBannerProps) {
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
  const existingPrUrl =
    report.implementation_pr_url ??
    (continuableTask ? getTaskPrUrl(continuableTask) : null);
  const hasExistingPr = !!existingPrUrl || !!continuableTask;

  const verdict = deriveReportVerdict(report, { hasExistingPr });

  const fireAction = useReportActionTracker(report);
  const openTask = useOpenTask();

  const { createPrReport, isCreatingPr } = useCreatePrReport({
    reportId: report.id,
    reportTitle: report.title ?? null,
    cloudRepository,
  });

  const [prOpen, setPrOpen] = useState(false);
  const [prFeedback, setPrFeedback] = useState("");

  const handleCreatePr = useCallback(() => {
    const trimmed = prFeedback.trim();
    fireAction("create_pr", {
      has_feedback: trimmed.length > 0,
      ...(trimmed ? { feedback_text: trimmed.slice(0, 500) } : {}),
    });
    setPrFeedback("");
    setPrOpen(false);
    void createPrReport(trimmed || undefined);
  }, [createPrReport, fireAction, prFeedback]);

  const handleContinuePr = useCallback(() => {
    if (!continuableTask) return;
    fireAction("open_pr");
    void openTask(continuableTask);
  }, [continuableTask, fireAction, openTask]);

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

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-lg border p-4",
        TONE_CLASS[verdict.tone],
      )}
    >
      <div className="flex flex-col gap-1">
        <span className="flex items-center gap-2 font-semibold text-[14px] text-gray-12">
          {verdict.tone === "progress" && <Spinner />}
          {verdict.title}
        </span>
        <span className="text-[13px] text-gray-11">{verdict.body}</span>
      </div>

      {showActions && (
        <div className="flex flex-wrap items-center gap-2.5">
          {hasExistingPr ? (
            <>
              <Button
                type="button"
                variant="primary"
                disabled={isCreatingPr || !continuableTask}
                onClick={handleContinuePr}
                className={BIG_BUTTON}
              >
                {reportTasksLoading && !continuableTask ? (
                  <Spinner />
                ) : (
                  <GitPullRequestIcon size={15} />
                )}
                Continue existing PR
              </Button>
              {existingPrUrl && (
                <a
                  href={existingPrUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-(--accent-11) text-[12px] hover:underline"
                >
                  <ArrowSquareOutIcon size={12} />
                  View PR on GitHub
                </a>
              )}
            </>
          ) : (
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
                    className={BIG_BUTTON}
                  >
                    {isCreatingPr ? (
                      <Spinner />
                    ) : (
                      <GitPullRequestIcon size={15} />
                    )}
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
                <Textarea
                  aria-label="Optional direction for the agent"
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
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] text-gray-10">
                    {isMac ? "⌘↵" : "Ctrl+↵"} to create
                  </span>
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={isCreatingPr}
                    onClick={handleCreatePr}
                  >
                    Create PR
                  </Button>
                </div>
              </PopoverContent>
            </Popover>
          )}
        </div>
      )}
    </div>
  );
}
