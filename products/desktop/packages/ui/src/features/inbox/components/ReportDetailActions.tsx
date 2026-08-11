import {
  ArrowSquareOutIcon,
  CaretDownIcon,
  ChatCircleIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import { canCreateImplementationPr } from "@posthog/core/inbox/reportActions";
import { Button } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { useCreatePrReport } from "@posthog/ui/features/inbox/hooks/useCreatePrReport";
import { useDiscussReport } from "@posthog/ui/features/inbox/hooks/useDiscussReport";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import {
  findContinuableImplementationTask,
  getTaskPrUrl,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useOpenTask } from "@posthog/ui/router/useOpenTask";
import { Flex, Popover, Spinner, Text, TextArea } from "@radix-ui/themes";
import { useCallback, useState } from "react";

interface ReportDetailActionsProps {
  report: SignalReport;
}

const isMac =
  typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

export function ReportDetailActions({ report }: ReportDetailActionsProps) {
  const canCreatePr = canCreateImplementationPr(report);
  // Resolved reports are terminal — their PR already merged, so no actions apply.
  const isResolved = report.status === "resolved";
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

  const fireAction = useReportActionTracker(report);
  const openTask = useOpenTask();

  const { discussReport, isDiscussing } = useDiscussReport({
    reportId: report.id,
    reportTitle: report.title ?? null,
    cloudRepository,
  });

  const { createPrReport, isCreatingPr } = useCreatePrReport({
    reportId: report.id,
    reportTitle: report.title ?? null,
    cloudRepository,
  });

  const [discussQuestion, setDiscussQuestion] = useState("");
  const [discussOpen, setDiscussOpen] = useState(false);
  const [prOpen, setPrOpen] = useState(false);
  const [prFeedback, setPrFeedback] = useState("");

  const submitDiscuss = useCallback(() => {
    const trimmed = discussQuestion.trim();
    if (!trimmed) return;
    fireAction("discuss", {
      has_question: true,
      question_text: trimmed.slice(0, 500),
    });
    setDiscussQuestion("");
    setDiscussOpen(false);
    void discussReport(trimmed);
  }, [discussQuestion, discussReport, fireAction]);

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
    setPrOpen(false);
    void openTask(continuableTask);
  }, [continuableTask, fireAction, openTask]);

  const submitDisabled = discussQuestion.trim().length === 0 || isDiscussing;

  // Show the PR action whenever the report can start one, or already has live
  // work to continue (the latter also covers the Pull requests tab, where
  // `canCreateImplementationPr` is false because a PR URL is set).
  const showPr = canCreatePr || hasExistingPr;

  // Terminal reports get no detail actions (guarded after hooks to satisfy rules-of-hooks).
  if (isResolved) {
    return null;
  }

  return (
    <>
      <Popover.Root
        open={discussOpen}
        onOpenChange={(next) => {
          setDiscussOpen(next);
          if (!next) setDiscussQuestion("");
        }}
      >
        <Popover.Trigger>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isDiscussing}
            className="gap-1"
            title="Discuss this report with your agent"
          >
            {isDiscussing ? <Spinner size="1" /> : <ChatCircleIcon size={12} />}
            Discuss
            <CaretDownIcon size={12} />
          </Button>
        </Popover.Trigger>
        <Popover.Content
          align="end"
          side="bottom"
          sideOffset={6}
          className="w-[420px] border border-(--gray-6) bg-(--color-panel-solid) p-3 shadow-6"
        >
          <form
            className="flex flex-col gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              submitDiscuss();
            }}
          >
            <TextArea
              aria-label="Question to discuss with the agent"
              autoFocus
              placeholder="Ask about this report…"
              resize="vertical"
              rows={5}
              size="2"
              value={discussQuestion}
              onChange={(event) => setDiscussQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  submitDiscuss();
                }
              }}
            />
            <Flex justify="between" align="center" gap="2">
              <Text size="1" color="gray">
                {isMac ? "⌘↵" : "Ctrl+↵"} to send
              </Text>
              <Flex gap="2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setDiscussOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={submitDisabled}
                >
                  Discuss
                </Button>
              </Flex>
            </Flex>
          </form>
        </Popover.Content>
      </Popover.Root>

      {showPr && (
        <Popover.Root
          open={prOpen}
          onOpenChange={(next) => {
            setPrOpen(next);
            if (!next) setPrFeedback("");
          }}
        >
          <Popover.Trigger>
            <Button
              type="button"
              variant="primary"
              size="sm"
              disabled={isCreatingPr}
              className="gap-1"
              title={
                hasExistingPr
                  ? "Continue the existing PR or open a new one"
                  : "Have Self-driving open a pull request for this report"
              }
            >
              {isCreatingPr ? (
                <Spinner size="1" />
              ) : (
                <GitPullRequestIcon size={12} />
              )}
              {hasExistingPr ? "Continue PR" : "Create PR"}
              <CaretDownIcon size={12} />
            </Button>
          </Popover.Trigger>
          <Popover.Content
            align="end"
            side="bottom"
            sideOffset={6}
            className="flex w-[420px] flex-col gap-3 border border-(--gray-6) bg-(--color-panel-solid) p-3 shadow-6"
          >
            {hasExistingPr && (
              <Flex direction="column" gap="2">
                <Text size="1" color="gray">
                  This report already has an open pull request. Continue it to
                  keep work on the same branch instead of opening a duplicate.
                </Text>
                {existingPrUrl && (
                  <a
                    href={existingPrUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-(--accent-11) text-[11px] hover:underline"
                  >
                    <ArrowSquareOutIcon size={11} />
                    View existing PR
                  </a>
                )}
                {(continuableTask || reportTasksLoading) && (
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={isCreatingPr || !continuableTask}
                    onClick={handleContinuePr}
                    title="Resume the existing implementation task"
                  >
                    {reportTasksLoading && !continuableTask ? (
                      <Spinner size="1" />
                    ) : (
                      <GitPullRequestIcon size={12} />
                    )}
                    Continue existing PR
                  </Button>
                )}
                <div className="h-px bg-(--gray-5)" />
              </Flex>
            )}
            <Flex direction="column" gap="2">
              <TextArea
                aria-label="Optional direction for the agent"
                autoFocus={!hasExistingPr}
                placeholder="Add direction for the agent (optional)…"
                resize="vertical"
                rows={4}
                size="2"
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
              <Flex justify="between" align="center" gap="2">
                <Text size="1" color="gray">
                  {isMac ? "⌘↵" : "Ctrl+↵"} to{" "}
                  {hasExistingPr ? "open new" : "create"}
                </Text>
                <Button
                  type="button"
                  variant={hasExistingPr ? "outline" : "primary"}
                  size="sm"
                  disabled={isCreatingPr}
                  onClick={handleCreatePr}
                >
                  {hasExistingPr ? "Open a new PR" : "Create PR"}
                </Button>
              </Flex>
            </Flex>
          </Popover.Content>
        </Popover.Root>
      )}
    </>
  );
}
