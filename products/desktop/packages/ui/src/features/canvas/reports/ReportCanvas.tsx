import {
  ArrowLeftIcon,
  ArrowSquareOutIcon,
  ChatCircleIcon,
  CheckCircleIcon,
  CircleNotchIcon,
  FileTextIcon,
  GitPullRequestIcon,
  MagnifyingGlassIcon,
  QuestionIcon,
} from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import {
  Badge,
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Text,
} from "@posthog/quill";
import type {
  AnySignalReportArtefact,
  Signal,
  SignalReport,
  Task,
  TaskRunStatus,
} from "@posthog/shared/types";
import { SignalReportSummaryMarkdown } from "@posthog/ui/features/inbox/components/utils/SignalReportSummaryMarkdown";
import { useDiscussReport } from "@posthog/ui/features/inbox/hooks/useDiscussReport";
import {
  useInboxReportArtefacts,
  useInboxReportById,
  useInboxReportSignals,
} from "@posthog/ui/features/inbox/hooks/useInboxReports";
import {
  findLatestDiscussionTask,
  getTaskPrUrl,
  type ReportTaskData,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

function reportStatus(report: SignalReport): {
  label: string;
  variant: "default" | "info" | "warning" | "success";
} {
  if (report.implementation_pr_url) {
    return { label: "PR created", variant: "success" };
  }
  switch (report.status) {
    case "in_progress":
      return { label: "Investigating", variant: "info" };
    case "pending_input":
      return { label: "Needs input", variant: "warning" };
    case "resolved":
      return { label: "Resolved", variant: "success" };
    case "suppressed":
      return { label: "Archived", variant: "default" };
    default:
      return { label: "Ready", variant: "default" };
  }
}

function latestExplanation(
  artefacts: AnySignalReportArtefact[],
  type: "actionability_judgment" | "priority_judgment",
): string | null {
  const match = [...artefacts].reverse().find((entry) => entry.type === type);
  if (!match || !("explanation" in match.content)) return null;
  return match.content.explanation;
}

function conversationPrompts(report: SignalReport): string[] {
  if (report.implementation_pr_url) {
    return [
      "Review the PR and summarize any remaining risks.",
      "Explain how the PR addresses this report.",
    ];
  }
  if (report.status === "pending_input") {
    return [
      "What input do you need from me?",
      "Continue investigating with the evidence you have.",
    ];
  }
  if (
    report.actionability === "immediately_actionable" &&
    report.already_addressed !== true
  ) {
    return ["Explain the recommended change.", "Implement this and open a PR."];
  }
  return ["Explain what you found.", "Investigate the next step."];
}

function runStatus(status: TaskRunStatus | undefined): {
  label: string;
  variant: "default" | "info" | "warning" | "success";
} {
  switch (status) {
    case "in_progress":
    case "queued":
      return { label: "Running", variant: "info" };
    case "completed":
      return { label: "Completed", variant: "success" };
    case "failed":
    case "cancelled":
      return { label: "Stopped", variant: "warning" };
    default:
      return { label: "Not started", variant: "default" };
  }
}

function ReportBrief({
  report,
  signals,
  artefacts,
  reportTasks,
}: {
  report: SignalReport;
  signals: Signal[];
  artefacts: AnySignalReportArtefact[];
  reportTasks: ReportTaskData[];
}) {
  const actionabilityExplanation = latestExplanation(
    artefacts,
    "actionability_judgment",
  );
  const priorityExplanation = latestExplanation(artefacts, "priority_judgment");
  const assessment = actionabilityExplanation ?? priorityExplanation;
  const evidence = signals.slice(0, 2);
  const pipelineTasks = reportTasks.filter(
    (entry) => entry.purpose !== "discussion",
  );
  const implementationPrUrl = report.implementation_pr_url;

  return (
    <aside className="flex h-full min-h-0 flex-col border-l bg-surface-primary">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b px-4">
        <FileTextIcon size={16} />
        <h2 className="font-semibold">Report brief</h2>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {report.status === "pending_input" && (
          <section className="border-warning/40 border-b bg-warning/5 p-4">
            <div className="mb-2 flex items-center gap-2">
              <QuestionIcon size={16} />
              <h3 className="font-semibold text-sm">Your input is needed</h3>
            </div>
            <Text size="sm">
              {actionabilityExplanation ??
                "Ask the agent what information it needs to continue."}
            </Text>
          </section>
        )}

        {implementationPrUrl && (
          <section className="border-b p-4">
            <div className="mb-3 flex items-start gap-3">
              <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-surface-secondary">
                <GitPullRequestIcon size={17} />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-sm">A fix is ready</h3>
                <Text variant="muted" size="xs">
                  Review the pull request or discuss it with the agent.
                </Text>
              </div>
            </div>
            <Button
              variant="primary"
              size="sm"
              className="w-full"
              onClick={() => openExternalUrl(implementationPrUrl)}
            >
              Review PR <ArrowSquareOutIcon size={14} />
            </Button>
          </section>
        )}

        <section className="border-b p-4">
          <h3 className="mb-2 font-semibold text-sm">What happened</h3>
          <SignalReportSummaryMarkdown
            content={report.summary}
            fallback="The agent is still investigating this report."
            variant="detail"
            pending={report.status === "in_progress"}
          />
        </section>

        {assessment && report.status !== "pending_input" && (
          <section className="border-b p-4">
            <div className="mb-2 flex items-center gap-2">
              {report.actionability ? (
                <CheckCircleIcon size={15} />
              ) : (
                <QuestionIcon size={15} />
              )}
              <h3 className="font-semibold text-sm">Current assessment</h3>
            </div>
            <Text size="sm">{assessment}</Text>
          </section>
        )}

        {!assessment &&
          !report.actionability &&
          report.status !== "pending_input" && (
            <section className="border-b p-4">
              <div className="mb-2 flex items-center gap-2">
                <QuestionIcon size={15} />
                <h3 className="font-semibold text-sm">What is still unclear</h3>
              </div>
              <Text size="sm">
                The agent is still gathering enough evidence to recommend a next
                step.
              </Text>
            </section>
          )}

        <section className="border-b p-4">
          <div className="mb-3 flex items-center gap-2">
            <MagnifyingGlassIcon size={15} />
            <h3 className="font-semibold text-sm">Evidence</h3>
            <Text variant="muted" size="xs" className="ml-auto">
              {signals.length || report.signal_count}
            </Text>
          </div>
          {evidence.length > 0 ? (
            <div className="flex flex-col gap-3">
              {evidence.map((signal) => (
                <div key={signal.signal_id} className="border-l-2 pl-3">
                  <Text size="sm">{signal.content}</Text>
                  <Text variant="muted" size="xs" className="mt-1">
                    {signal.source_product.replaceAll("_", " ")}
                  </Text>
                </div>
              ))}
              {signals.length > evidence.length && (
                <Text variant="muted" size="xs">
                  {signals.length - evidence.length} more supporting signals
                </Text>
              )}
            </div>
          ) : (
            <Text variant="muted" size="sm">
              Evidence will appear as the investigation progresses.
            </Text>
          )}
        </section>

        {pipelineTasks.length > 0 && (
          <section className="p-4">
            <div className="mb-3 flex items-center gap-2">
              <CircleNotchIcon size={15} />
              <h3 className="font-semibold text-sm">Activity</h3>
            </div>
            <div className="flex flex-col gap-4">
              {pipelineTasks.map((entry) => {
                const status = runStatus(entry.task.latest_run?.status);
                const prUrl = getTaskPrUrl(entry.task);
                return (
                  <div key={entry.task.id} className="flex items-start gap-3">
                    <div className="mt-1 size-2 shrink-0 rounded-full bg-current opacity-50" />
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <Text size="sm" className="font-medium">
                          {entry.purposeLabel}
                        </Text>
                        <Badge variant={status.variant}>{status.label}</Badge>
                      </div>
                      <Text variant="muted" size="xs">
                        {entry.task.title || "Untitled task"}
                      </Text>
                      {prUrl && (
                        <Button
                          variant="link-muted"
                          size="sm"
                          className="mt-1 h-auto p-0"
                          onClick={() => openExternalUrl(prUrl)}
                        >
                          Open PR <ArrowSquareOutIcon size={12} />
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </aside>
  );
}

export function ReportWorkspaceView({
  report,
  signals,
  artefacts,
  reportTasks,
  conversation,
}: {
  report: SignalReport;
  signals: Signal[];
  artefacts: AnySignalReportArtefact[];
  reportTasks: ReportTaskData[];
  conversation: ReactNode;
}) {
  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
      <main className="min-h-0 min-w-0 bg-surface-secondary p-3">
        <div className="h-full min-h-0 overflow-hidden rounded-lg border bg-surface-primary">
          {conversation}
        </div>
      </main>
      <ReportBrief
        report={report}
        signals={signals}
        artefacts={artefacts}
        reportTasks={reportTasks}
      />
    </div>
  );
}

function NewReportConversation({
  report,
  isStarting,
  onPrompt,
}: {
  report: SignalReport;
  isStarting: boolean;
  onPrompt: (prompt: string) => void;
}) {
  const prompts = conversationPrompts(report);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b px-4">
        <ChatCircleIcon size={16} />
        <h2 className="font-semibold">Conversation</h2>
      </div>
      <div className="flex min-h-0 flex-1 flex-col justify-end">
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="flex max-w-lg flex-col items-center text-center">
            <div className="mb-4 flex size-10 items-center justify-center rounded-full border bg-surface-secondary">
              <ChatCircleIcon size={20} />
            </div>
            <h3 className="font-semibold text-lg">Discuss this report</h3>
            <Text variant="muted" size="sm" className="mt-1 max-w-md">
              The agent has the report, its evidence, and any work already
              completed.
            </Text>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {prompts.map((prompt) => (
                <Button
                  key={prompt}
                  variant="outline"
                  size="sm"
                  disabled={isStarting}
                  onClick={() => onPrompt(prompt)}
                >
                  {prompt}
                </Button>
              ))}
            </div>
          </div>
        </div>
        <div className="border-t p-3">
          <PromptInput
            sessionId={`report:${report.id}`}
            placeholder="Ask about this report..."
            editorHeight="large"
            hideDefaultToolbar
            disabled={isStarting}
            isLoading={isStarting}
            clearOnSubmit
            onSubmit={onPrompt}
          />
        </div>
      </div>
    </div>
  );
}

export function ReportCanvas({
  channelId,
  reportId,
}: {
  channelId: string;
  reportId: string;
}) {
  const reportQuery = useInboxReportById(reportId);
  const signalsQuery = useInboxReportSignals(reportId);
  const artefactsQuery = useInboxReportArtefacts(reportId);
  const report = reportQuery.data;
  const reportTasksQuery = useReportTasks(
    reportId,
    report?.status ?? "candidate",
  );
  const reportTasks = useMemo(
    () => reportTasksQuery.data ?? [],
    [reportTasksQuery.data],
  );
  const persistedDiscussionTask = findLatestDiscussionTask(reportTasks);
  const [createdDiscussionTask, setCreatedDiscussionTask] =
    useState<Task | null>(null);
  const discussionTask = createdDiscussionTask ?? persistedDiscussionTask;
  const repository = extractRepoSelectionRepository(
    artefactsQuery.data?.results,
  );
  const { discussReport, isDiscussing } = useDiscussReport({
    reportId,
    reportTitle: report?.title ?? null,
    cloudRepository: repository,
    allowMissingRepository: true,
    redirectOnSuccess: false,
    onTaskCreated: setCreatedDiscussionTask,
  });

  useEffect(() => {
    if (persistedDiscussionTask) setCreatedDiscussionTask(null);
  }, [persistedDiscussionTask]);

  if (reportQuery.isLoading && !report) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (!report) {
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileTextIcon />
          </EmptyMedia>
          <EmptyTitle>Report not found</EmptyTitle>
          <EmptyDescription>
            This report may have been removed. Return to the space and choose
            another report.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  const startConversation = (prompt: string) => {
    if (!prompt.trim() || isDiscussing) return;
    void discussReport(prompt);
  };
  const status = reportStatus(report);

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-primary">
      <header className="flex min-h-14 shrink-0 items-center gap-3 border-b px-3 py-2">
        <Button
          variant="default"
          size="icon"
          aria-label="Back to space"
          render={<Link to="/website/$channelId" params={{ channelId }} />}
        >
          <ArrowLeftIcon size={15} />
        </Button>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <h1 className="truncate font-semibold">
              {report.title || "Untitled report"}
            </h1>
            <Badge variant={status.variant}>{status.label}</Badge>
            {report.priority && <Badge>{report.priority}</Badge>}
          </div>
          <Text variant="muted" size="xs">
            Report session
          </Text>
        </div>
      </header>
      <div className="min-h-0 flex-1">
        <ReportWorkspaceView
          report={report}
          signals={signalsQuery.data?.signals ?? []}
          artefacts={artefactsQuery.data?.results ?? []}
          reportTasks={reportTasks}
          conversation={
            discussionTask ? (
              <EmbeddedSessionView task={discussionTask} isActiveSession />
            ) : (
              <NewReportConversation
                report={report}
                isStarting={isDiscussing}
                onPrompt={startConversation}
              />
            )
          }
        />
      </div>
    </div>
  );
}
