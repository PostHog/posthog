import {
  ArrowLeftIcon,
  ArrowSquareOutIcon,
  ChatCircleIcon,
  CheckCircleIcon,
  CircleNotchIcon,
  FileTextIcon,
  GitPullRequestIcon,
  LightbulbIcon,
  MagnifyingGlassIcon,
  QuestionIcon,
} from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import {
  Badge,
  Button,
  Card,
  CardContent,
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
  type ReportTaskData,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { Link } from "@tanstack/react-router";
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

function suggestedPrompt(report: SignalReport): string {
  if (report.implementation_pr_url) {
    return "Review the existing PR and tell me what still needs attention.";
  }
  if (report.status === "pending_input") {
    return "What input do you need from me to move this forward?";
  }
  if (
    report.actionability === "immediately_actionable" &&
    report.already_addressed !== true
  ) {
    return "Implement the recommended change and open a PR.";
  }
  if (report.actionability === "not_actionable") {
    return "Explain why this is not actionable and what would change that assessment.";
  }
  return "Investigate this further and recommend the next step.";
}

function latestExplanation(
  artefacts: AnySignalReportArtefact[],
  type: "actionability_judgment" | "priority_judgment",
): string | null {
  const match = [...artefacts].reverse().find((entry) => entry.type === type);
  if (!match || !("explanation" in match.content)) return null;
  return match.content.explanation;
}

export function ReportStoryCanvas({
  report,
  signals,
  artefacts,
  reportTasks,
  onPrompt,
  isStartingConversation = false,
}: {
  report: SignalReport;
  signals: Signal[];
  artefacts: AnySignalReportArtefact[];
  reportTasks: ReportTaskData[];
  onPrompt: (prompt: string) => void;
  isStartingConversation?: boolean;
}) {
  const status = reportStatus(report);
  const actionabilityExplanation = latestExplanation(
    artefacts,
    "actionability_judgment",
  );
  const priorityExplanation = latestExplanation(artefacts, "priority_judgment");
  const hasUncertainty =
    report.status === "candidate" ||
    report.status === "in_progress" ||
    !report.actionability;
  const prompt = suggestedPrompt(report);
  const visibleSignals = signals.slice(0, 3);
  const implementationPrUrl = report.implementation_pr_url;
  const pipelineTasks = reportTasks.filter(
    (entry) => entry.purpose !== "discussion",
  );

  return (
    <div className="h-full overflow-y-auto bg-surface-primary">
      <main className="mx-auto flex w-full max-w-5xl flex-col gap-5 px-6 py-6">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={status.variant}>{status.label}</Badge>
          {report.priority && <Badge>{report.priority}</Badge>}
          {report.source_products?.map((product) => (
            <Badge key={product}>{product.replaceAll("_", " ")}</Badge>
          ))}
        </div>

        <header className="max-w-3xl">
          <Text variant="muted" size="sm">
            Report
          </Text>
          <h1 className="mt-1 text-balance font-semibold text-3xl leading-tight">
            {report.title || "Untitled report"}
          </h1>
        </header>

        <Card>
          <CardContent className="p-6">
            <div className="mb-3 flex items-center gap-2">
              <LightbulbIcon size={18} />
              <h2 className="font-semibold text-lg">What we found</h2>
            </div>
            <div className="max-w-3xl text-base leading-relaxed">
              <SignalReportSummaryMarkdown
                content={report.summary}
                fallback="The agent is still investigating this report."
                variant="detail"
                pending={report.status === "in_progress"}
              />
            </div>
          </CardContent>
        </Card>

        {implementationPrUrl && (
          <Card>
            <CardContent className="flex flex-wrap items-center gap-4 p-5">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-surface-secondary">
                <GitPullRequestIcon size={20} />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="font-semibold">A fix is ready to review</h2>
                <Text variant="muted" size="sm">
                  The self-driving pipeline created a pull request for this
                  report.
                </Text>
              </div>
              <Button
                variant="primary"
                size="sm"
                onClick={() => openExternalUrl(implementationPrUrl)}
              >
                Review PR <ArrowSquareOutIcon size={14} />
              </Button>
            </CardContent>
          </Card>
        )}

        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardContent className="p-5">
              <div className="mb-4 flex items-center gap-2">
                <MagnifyingGlassIcon size={17} />
                <h2 className="font-semibold">Evidence</h2>
                <Text variant="muted" size="xs" className="ml-auto">
                  {signals.length || report.signal_count}{" "}
                  {(signals.length || report.signal_count) === 1
                    ? "signal"
                    : "signals"}
                </Text>
              </div>
              {visibleSignals.length > 0 ? (
                <div className="flex flex-col gap-3">
                  {visibleSignals.map((signal) => (
                    <div
                      key={signal.signal_id}
                      className="rounded-lg border bg-surface-secondary p-3"
                    >
                      <div className="mb-1 flex items-center gap-2">
                        <Badge>
                          {signal.source_product.replaceAll("_", " ")}
                        </Badge>
                        <Text variant="muted" size="xs">
                          {signal.source_type.replaceAll("_", " ")}
                        </Text>
                      </div>
                      <Text size="sm">{signal.content}</Text>
                    </div>
                  ))}
                  {signals.length > visibleSignals.length && (
                    <Text variant="muted" size="xs">
                      {signals.length - visibleSignals.length} more signals
                      support this report.
                    </Text>
                  )}
                </div>
              ) : (
                <Text variant="muted" size="sm">
                  Evidence will appear here as the investigation progresses.
                </Text>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="mb-4 flex items-center gap-2">
                {hasUncertainty ? (
                  <QuestionIcon size={17} />
                ) : (
                  <CheckCircleIcon size={17} />
                )}
                <h2 className="font-semibold">
                  {hasUncertainty ? "What is still unclear" : "Assessment"}
                </h2>
              </div>
              <div className="flex flex-col gap-3">
                <Text size="sm">
                  {actionabilityExplanation ??
                    priorityExplanation ??
                    (hasUncertainty
                      ? "The report does not have enough evidence for a firm recommendation yet."
                      : "The report has enough evidence to recommend a next step.")}
                </Text>
                {report.already_addressed === true && (
                  <div className="flex items-center gap-2 rounded-lg border bg-surface-secondary p-3">
                    <CheckCircleIcon size={16} />
                    <Text size="sm">This may already be addressed.</Text>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {pipelineTasks.length > 0 && (
          <Card>
            <CardContent className="p-5">
              <div className="mb-3 flex items-center gap-2">
                <CircleNotchIcon size={17} />
                <h2 className="font-semibold">Work so far</h2>
              </div>
              <div className="flex flex-wrap gap-2">
                {pipelineTasks.map((entry) => (
                  <Badge key={entry.task.id}>{entry.purposeLabel}</Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        <Card className="border-primary/30 bg-primary/5">
          <CardContent className="flex flex-wrap items-center gap-4 p-5">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <ChatCircleIcon size={20} />
            </div>
            <div className="min-w-0 flex-1">
              <Text variant="muted" size="xs">
                Recommended next step
              </Text>
              <p className="font-medium">{prompt}</p>
            </div>
            <Button
              variant="primary"
              size="sm"
              loading={isStartingConversation}
              disabled={isStartingConversation}
              onClick={() => onPrompt(prompt)}
            >
              Ask the agent
            </Button>
          </CardContent>
        </Card>
      </main>
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
  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-primary">
      <div className="border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <ChatCircleIcon size={17} />
          <h2 className="font-semibold">Conversation</h2>
        </div>
        <Text variant="muted" size="xs">
          The agent will receive this report and its evidence.
        </Text>
      </div>
      <div className="flex min-h-0 flex-1 flex-col justify-end gap-4 p-4">
        <div className="rounded-lg border bg-surface-secondary p-4">
          <Text size="sm">
            Ask a question, investigate the finding, or tell the agent to act on
            it.
          </Text>
        </div>
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

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-primary">
      <div className="flex h-10 shrink-0 items-center border-b px-3">
        <Button
          variant="link-muted"
          size="sm"
          render={<Link to="/website/$channelId" params={{ channelId }} />}
        >
          <ArrowLeftIcon size={14} /> Back to space
        </Button>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(320px,400px)]">
        <div className="min-h-0 min-w-0 border-r">
          <ReportStoryCanvas
            report={report}
            signals={signalsQuery.data?.signals ?? []}
            artefacts={artefactsQuery.data?.results ?? []}
            reportTasks={reportTasks}
            onPrompt={startConversation}
            isStartingConversation={isDiscussing}
          />
        </div>
        <aside className="min-h-0 min-w-0">
          {discussionTask ? (
            <EmbeddedSessionView task={discussionTask} isActiveSession />
          ) : (
            <NewReportConversation
              report={report}
              isStarting={isDiscussing}
              onPrompt={startConversation}
            />
          )}
        </aside>
      </div>
    </div>
  );
}
