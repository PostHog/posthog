import {
  ArrowRightIcon,
  CaretDownIcon,
  CopyIcon,
  FileTextIcon,
  GitPullRequestIcon,
  MagnifyingGlassIcon,
  TerminalIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import {
  deriveHeadline,
  parsePrUrl,
} from "@posthog/core/inbox/reportPresentation";
import { Button } from "@posthog/quill";
import {
  isTerminalStatus,
  type SignalReport,
  type TaskRunStatus,
} from "@posthog/shared/types";
import {
  RUN_VARIANT_TIMESTAMP_LABEL,
  resolveRunVariant,
} from "@posthog/ui/features/inbox/components/AgentRunCard";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { ReportActivitySection } from "@posthog/ui/features/inbox/components/detail/ReportActivitySection";
import { InboxDetailPageHeader } from "@posthog/ui/features/inbox/components/InboxDetailPageHeader";
import {
  InboxMetaSeparator,
  InboxMetaText,
} from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { InboxMetaSourceStack } from "@posthog/ui/features/inbox/components/InboxMetaSourceStack";
import { InboxReportDetailGate } from "@posthog/ui/features/inbox/components/InboxReportDetailGate";
import { PrDiffStats } from "@posthog/ui/features/inbox/components/PrDiffStats";
import { RightColumnSection } from "@posthog/ui/features/inbox/components/RightColumnSection";
import {
  SignalsList,
  SignalsListSkeleton,
} from "@posthog/ui/features/inbox/components/SignalsList";
import { ForYouBadge } from "@posthog/ui/features/inbox/components/utils/ForYouBadge";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { SignalReportPriorityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge";
import { SignalReportSummaryMarkdown } from "@posthog/ui/features/inbox/components/utils/SignalReportSummaryMarkdown";
import {
  getSourceProductMeta,
  hasKnownSourceProduct,
} from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { useInboxReportSignals } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import {
  type ReportTaskData,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import { TaskLogsPanel } from "@posthog/ui/features/task-detail/components/TaskLogsPanel";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { DropdownMenu, Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";

export function TaskRunStatusDot({ status }: { status: TaskRunStatus }) {
  const terminal = isTerminalStatus(status);
  const color = terminal
    ? status === "failed" || status === "cancelled"
      ? "bg-(--red-9)"
      : "bg-(--green-9)"
    : "bg-(--blue-9)";
  const animate = terminal ? "" : " animate-pulse";
  return (
    <span
      className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${color}${animate}`}
      aria-hidden
    />
  );
}

/** Prefer in-motion tasks; tie-break by most-recently-created. */
function pickPrimaryTask(tasks: ReportTaskData[]): ReportTaskData | null {
  if (tasks.length === 0) return null;
  return [...tasks].sort((a, b) => {
    const aInMotion = !isTerminalStatus(a.task.latest_run?.status ?? "");
    const bInMotion = !isTerminalStatus(b.task.latest_run?.status ?? "");
    if (aInMotion !== bInMotion) return aInMotion ? -1 : 1;
    return new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime();
  })[0];
}

function RunOutputWidget({ report }: { report: SignalReport }) {
  if (report.status === "ready") {
    return <RunOutputReadyCard report={report} />;
  }

  if (report.status === "failed") {
    return (
      <Flex
        align="center"
        gap="3"
        className="rounded-(--radius-2) border border-(--red-5) bg-(--red-2) px-4 py-3.5"
      >
        <Flex
          align="center"
          justify="center"
          className="h-9 w-9 shrink-0 rounded-full bg-(--red-3) ring-(--red-6) ring-1 ring-inset"
        >
          <WarningIcon size={16} className="text-(--red-11)" />
        </Flex>
        <Flex direction="column" gap="0.5" className="min-w-0 flex-1">
          <Text className="font-medium text-[13px] text-gray-12">
            Run failed
          </Text>
          <Text className="text-[12px] text-gray-11 leading-snug">
            Research couldn't complete – check the task log below for the error.
            The Responder may retry automatically.
          </Text>
        </Flex>
      </Flex>
    );
  }

  return (
    <DetailSection Icon={FileTextIcon} title="Draft summary">
      <SignalReportSummaryMarkdown
        content={report.summary}
        fallback={
          report.status === "in_progress"
            ? "The Responder is investigating – partial findings will appear here as they land."
            : "Queued for research."
        }
        variant="detail"
        pending={report.status === "in_progress"}
      />
    </DetailSection>
  );
}

function RunOutputReadyCard({ report }: { report: SignalReport }) {
  const prUrl = report.implementation_pr_url;
  const isPr = !!prUrl;
  const prRef = prUrl ? parsePrUrl(prUrl) : null;
  const sourceMeta = getSourceProductMeta(report.source_products?.[0]);
  const headline = deriveHeadline(report.summary);

  return (
    <Link
      to={
        isPr ? "/code/inbox/pulls/$reportId" : "/code/inbox/reports/$reportId"
      }
      params={{ reportId: report.id }}
      className="group block rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3.5 no-underline transition duration-150 hover:border-(--gray-6) hover:bg-(--gray-2) hover:shadow-sm focus-visible:outline-none"
    >
      <Flex direction="column" gap="2">
        <Flex align="center" gap="2" wrap="wrap">
          <Flex
            align="center"
            justify="center"
            className="h-5 w-5 shrink-0 rounded-full bg-(--green-2) ring-(--green-5) ring-1 ring-inset"
          >
            {isPr ? (
              <GitPullRequestIcon size={11} className="text-(--green-11)" />
            ) : (
              <FileTextIcon size={11} className="text-(--green-11)" />
            )}
          </Flex>
          {prRef ? (
            <Text className="font-mono text-[12.5px] text-gray-12">
              {prRef.repoSlug}#{prRef.number}
            </Text>
          ) : (
            <Text className="font-medium text-[13px] text-gray-12">Report</Text>
          )}
          <span className="flex-1" />
          {prUrl ? (
            <PrDiffStats prUrl={prUrl} hideWhileLoading />
          ) : sourceMeta ? (
            <Flex align="center" gap="1.5" className="text-[12px] text-gray-11">
              <span
                className="inline-flex shrink-0 items-center"
                style={{ color: sourceMeta.color }}
                aria-hidden
              >
                <sourceMeta.Icon size={12} />
              </span>
              <span>{sourceMeta.label}</span>
            </Flex>
          ) : null}
        </Flex>
        {(report.title || headline) && (
          <Text className="line-clamp-2 text-[12.5px] text-gray-11 leading-snug">
            {report.title || headline}
          </Text>
        )}
        <Flex align="center" gap="1" className="text-[12px] text-gray-10">
          <span>{isPr ? "Open the pull request" : "Open the report"}</span>
          <ArrowRightIcon
            size={12}
            className="transition-transform group-hover:translate-x-0.5"
          />
        </Flex>
      </Flex>
    </Link>
  );
}

interface AgentRunDetailProps {
  reportId: string;
}

export function AgentRunDetail({ reportId }: AgentRunDetailProps) {
  return (
    <InboxReportDetailGate
      reportId={reportId}
      backTo="/code/inbox/runs"
      backLabel="Back to runs"
      missingCopy="This run couldn't be found. It may have completed or been removed."
    >
      {(report) => <AgentRunDetailContent report={report} />}
    </InboxReportDetailGate>
  );
}

function AgentRunDetailContent({ report }: { report: SignalReport }) {
  const { data: signalsResp } = useInboxReportSignals(report.id);
  const { data: reportTasks, isLoading: isLoadingReportTasks } = useReportTasks(
    report.id,
    report.status,
  );
  const signals = signalsResp?.signals ?? [];
  const hasSource = hasKnownSourceProduct(report.source_products);
  const isLive = report.status === "in_progress";
  const headerVariant = resolveRunVariant(report);
  const headerTimestamp =
    headerVariant === "live"
      ? report.created_at
      : (report.updated_at ?? report.created_at);
  // UUIDs are time-based here, so the prefix collides across reports — show
  // the random tail segment instead so adjacent runs read as distinct.
  const runId = `…-${report.id.split("-").pop() ?? report.id}`;

  const primaryTask = useMemo(
    () => pickPrimaryTask(reportTasks ?? []),
    [reportTasks],
  );
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const selectedEntry =
    reportTasks?.find((rt) => rt.task.id === selectedTaskId) ?? primaryTask;
  const selectedTask = selectedEntry?.task ?? null;

  // Any prior terminal research counts — completed, failed, or cancelled —
  // because a re-run signals "we already tried, now we're trying again",
  // regardless of how the first attempt ended.
  const isReResearch = useMemo(() => {
    if (!reportTasks) return false;
    const researchTasks = reportTasks.filter((rt) => rt.purpose === "research");
    if (researchTasks.length < 2) return false;
    const hasInFlight = researchTasks.some(
      (rt) =>
        rt.task.latest_run?.status &&
        !isTerminalStatus(rt.task.latest_run.status),
    );
    const hasPriorTerminal = researchTasks.some((rt) =>
      isTerminalStatus(rt.task.latest_run?.status ?? ""),
    );
    return hasInFlight && hasPriorTerminal;
  }, [reportTasks]);

  return (
    <Flex direction="column" className="min-h-full">
      <InboxDetailPageHeader
        backTo="/code/inbox/runs"
        backLabel="Back to runs"
        breadcrumb={
          <>
            <span className="text-(--gray-8)">/</span>
            <Text className="font-mono text-[12px] text-gray-11">{runId}</Text>
          </>
        }
        reportTitle={report.title}
        fallbackTitle="Untitled run"
        badges={
          <>
            {isLive ? (
              <InboxBadge variant="info" className="gap-1.5">
                <span
                  className="block h-1.5 w-1.5 animate-pulse rounded-full bg-(--blue-9)"
                  aria-hidden
                />
                Running
              </InboxBadge>
            ) : (
              <InboxBadge variant="default">Finished</InboxBadge>
            )}
            {isReResearch && (
              <InboxBadge
                variant="warning"
                title="A prior research run on this report already completed – this is a re-attempt."
              >
                Re-research
              </InboxBadge>
            )}
            {report.priority && (
              <SignalReportPriorityBadge priority={report.priority} />
            )}
            {report.is_suggested_reviewer && <ForYouBadge />}
          </>
        }
        meta={
          <>
            <InboxMetaText>
              {RUN_VARIANT_TIMESTAMP_LABEL[headerVariant]}
            </InboxMetaText>
            <RelativeTimestamp
              timestamp={headerTimestamp}
              className="text-[12px]"
            />
            {hasSource && (
              <>
                <InboxMetaSeparator />
                <InboxMetaSourceStack
                  sourceProducts={report.source_products}
                  labelPrefix="Triggered by "
                />
              </>
            )}
            {signals.length > 0 && (
              <>
                <InboxMetaSeparator />
                <InboxMetaText className="tabular-nums">
                  {signals.length} finding{signals.length === 1 ? "" : "s"}
                </InboxMetaText>
              </>
            )}
          </>
        }
        actions={
          <>
            {selectedTask && (
              <Button
                type="button"
                variant="primary"
                size="sm"
                onClick={() => void openTask(selectedTask)}
              >
                Open task
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => copyInboxReportLink(report)}
              title="Copy a deep link to this run"
            >
              <CopyIcon size={12} />
              Copy link
            </Button>
          </>
        }
      />

      <div className="@container mx-auto w-full max-w-[calc(160ch+5rem)] px-6 py-5 text-[13px]">
        <div className="grid @4xl:grid-cols-[minmax(0,80ch)_minmax(0,1fr)] grid-cols-1 gap-5">
          <Flex direction="column" gap="5" className="min-w-0">
            <RunOutputWidget report={report} />

            <DetailSection
              Icon={TerminalIcon}
              title="Task log"
              rightSlot={
                <TaskLogRightSlot
                  entries={reportTasks ?? []}
                  selectedEntry={selectedEntry}
                  onSelect={(id) => setSelectedTaskId(id)}
                />
              }
            >
              {isLoadingReportTasks ? (
                <Flex direction="column" gap="2">
                  <span className="h-4 w-36 animate-pulse rounded bg-(--gray-3)" />
                  <span className="h-28 w-full animate-pulse rounded-(--radius-2) bg-(--gray-2)" />
                </Flex>
              ) : selectedTask ? (
                <div className="h-[calc(100vh-22rem)] min-h-[420px] w-full overflow-hidden rounded-(--radius-2) border border-border bg-(--color-panel-solid)">
                  <TaskLogsPanel
                    taskId={selectedTask.id}
                    task={selectedTask}
                    hideInput
                  />
                </div>
              ) : (
                <Flex
                  direction="column"
                  gap="2"
                  className="rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3.5"
                >
                  <Text className="font-medium text-[13px] text-gray-12">
                    Waiting for the linked task
                  </Text>
                  <Text className="max-w-2xl text-[12.5px] text-gray-11 leading-snug">
                    Once Self-driving links this run to a task, this panel will
                    show the same live log UI as the task detail page. No
                    separate mock log is shown here.
                  </Text>
                </Flex>
              )}
            </DetailSection>
          </Flex>

          <Flex direction="column" gap="5" className="min-w-0">
            {(signals.length > 0 || report.signal_count > 0) && (
              <RightColumnSection
                Icon={MagnifyingGlassIcon}
                title="Evidence so far"
                rightSlot={
                  <Text className="cursor-default select-none text-[11px] text-gray-10 tabular-nums">
                    {signals.length || report.signal_count} finding
                    {(signals.length || report.signal_count) === 1 ? "" : "s"}
                  </Text>
                }
              >
                {signals.length > 0 ? (
                  <SignalsList signals={signals} />
                ) : (
                  <SignalsListSkeleton count={report.signal_count} />
                )}
              </RightColumnSection>
            )}
            <ReportActivitySection reportId={report.id} />
          </Flex>
        </div>
      </div>
    </Flex>
  );
}

function TaskLogRightSlot({
  entries,
  selectedEntry,
  onSelect,
}: {
  entries: ReportTaskData[];
  selectedEntry: ReportTaskData | null | undefined;
  onSelect: (id: string) => void;
}) {
  if (!selectedEntry) return null;
  if (entries.length <= 1) {
    return (
      <Text className="font-mono text-[12px] text-gray-10">
        {selectedEntry.task.id}
      </Text>
    );
  }
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-(--radius-1) px-1.5 py-0.5 font-medium text-[12px] text-gray-11 hover:bg-(--gray-3) hover:text-gray-12 focus-visible:bg-(--gray-3) focus-visible:outline-none"
          aria-label="Switch task"
        >
          <TaskRunStatusDot
            status={selectedEntry.task.latest_run?.status ?? "not_started"}
          />
          {selectedEntry.purposeLabel}
          <CaretDownIcon size={12} className="text-gray-10" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end" sideOffset={4}>
        {entries.map((entry) => {
          const status = entry.task.latest_run?.status ?? "not_started";
          return (
            <DropdownMenu.Item
              key={entry.task.id}
              onSelect={() => onSelect(entry.task.id)}
            >
              <Flex align="center" gap="2" className="min-w-[200px]">
                <TaskRunStatusDot status={status} />
                <Text className="font-medium text-[12.5px]">
                  {entry.purposeLabel}
                </Text>
                <Text className="ml-auto font-mono text-[11px] text-gray-10">
                  {entry.task.id.slice(0, 8)}
                </Text>
              </Flex>
            </DropdownMenu.Item>
          );
        })}
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  );
}
