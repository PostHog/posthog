import { RobotIcon } from "@phosphor-icons/react";
import {
  INBOX_SCOPE_ENTIRE_PROJECT,
  INBOX_SCOPE_FOR_YOU,
  partitionRunsTabReports,
} from "@posthog/core/inbox/reportMembership";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { AgentRunCard } from "@posthog/ui/features/inbox/components/AgentRunCard";
import { CardSkeleton } from "@posthog/ui/features/inbox/components/CardSkeleton";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { Flex, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";

const RECENTLY_FINISHED_LIMIT = 10;
const QUEUED_LIMIT = 10;

export function RunsTab() {
  // Runs is project-wide and intentionally chrome-less. Reviewer assignment
  // is an output of research, so For-you would silently empty queued / live;
  // source and priority filters don't read as run-shaped questions either.
  // We pin ordering to newest-first locally too.
  const { scopedReports, isLoading } = useInboxAllReports({
    ignoreScope: true,
    ignoreFilters: true,
  });
  const scope = useInboxReviewerScopeStore((s) => s.scope);
  const [showAllFinished, setShowAllFinished] = useState(false);
  const [showAllQueued, setShowAllQueued] = useState(false);

  const { queuedRuns, liveRuns, finishedRuns } = useMemo(() => {
    const { queued, live, finished } = partitionRunsTabReports(scopedReports);
    return { queuedRuns: queued, liveRuns: live, finishedRuns: finished };
  }, [scopedReports]);

  const visibleFinishedRuns = showAllFinished
    ? finishedRuns
    : finishedRuns.slice(0, RECENTLY_FINISHED_LIMIT);
  const hiddenFinishedCount = Math.max(
    0,
    finishedRuns.length - visibleFinishedRuns.length,
  );
  const finishedShowAll = resolveShowAllControl(
    finishedRuns.length,
    RECENTLY_FINISHED_LIMIT,
    hiddenFinishedCount,
    showAllFinished,
    () => setShowAllFinished(true),
    () => setShowAllFinished(false),
  );

  const visibleQueuedRuns = showAllQueued
    ? queuedRuns
    : queuedRuns.slice(0, QUEUED_LIMIT);
  const hiddenQueuedCount = Math.max(
    0,
    queuedRuns.length - visibleQueuedRuns.length,
  );
  const queuedShowAll = resolveShowAllControl(
    queuedRuns.length,
    QUEUED_LIMIT,
    hiddenQueuedCount,
    showAllQueued,
    () => setShowAllQueued(true),
    () => setShowAllQueued(false),
  );

  if (isLoading && scopedReports.length === 0) {
    return (
      <Flex direction="column" gap="4" className="mx-auto max-w-3xl px-6 py-4">
        <Flex direction="column" gap="2">
          <span className="h-4 w-28 animate-pulse rounded bg-(--gray-3)" />
          <CardSkeleton count={3} variant="rows" />
        </Flex>
      </Flex>
    );
  }

  const hasAnyRuns =
    queuedRuns.length > 0 || liveRuns.length > 0 || finishedRuns.length > 0;

  return (
    <Flex direction="column" gap="4" className="mx-auto max-w-3xl px-6 py-4">
      {!hasAnyRuns ? (
        <Empty className="mx-auto max-w-md py-16">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <RobotIcon size={24} />
            </EmptyMedia>
            <EmptyTitle>
              {scope === INBOX_SCOPE_FOR_YOU
                ? "No Responders are working on something for you right now"
                : scope === INBOX_SCOPE_ENTIRE_PROJECT
                  ? "No Responders are working on anything in the project right now"
                  : "No Responders are working on something for this reviewer right now"}
            </EmptyTitle>
            <EmptyDescription>
              When Self-driving kicks one off, you'll see the live run land here
              until it finishes as a Pull request or a Report.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <Flex direction="column" gap="5">
          {queuedRuns.length > 0 && (
            <RunsSection
              title="Queued"
              count={queuedRuns.length}
              runs={visibleQueuedRuns}
              showAll={queuedShowAll}
            />
          )}
          <RunsSection
            title="Live"
            count={liveRuns.length}
            isLive
            runs={liveRuns}
            empty={{
              title: "Nothing in motion right now",
              description:
                "Self-driving will queue something up here when it kicks off a run.",
            }}
          />
          {finishedRuns.length > 0 && (
            <RunsSection
              title="Recently finished"
              count={finishedRuns.length}
              runs={visibleFinishedRuns}
              showAll={finishedShowAll}
            />
          )}
        </Flex>
      )}
    </Flex>
  );
}

type ShowAllControl =
  | { kind: "expand"; hiddenCount: number; onClick: () => void }
  | { kind: "collapse"; onClick: () => void };

function resolveShowAllControl(
  totalCount: number,
  limit: number,
  hiddenCount: number,
  expanded: boolean,
  onExpand: () => void,
  onCollapse: () => void,
): ShowAllControl | undefined {
  if (hiddenCount > 0)
    return { kind: "expand", hiddenCount, onClick: onExpand };
  if (expanded && totalCount > limit) {
    return { kind: "collapse", onClick: onCollapse };
  }
  return undefined;
}

interface RunsSectionProps {
  title: string;
  count: number;
  description?: string;
  isLive?: boolean;
  runs: ReturnType<typeof useInboxAllReports>["scopedReports"];
  empty?: { title: string; description: string };
  showAll?: ShowAllControl;
}

function RunsSection({
  title,
  count,
  description,
  isLive,
  runs,
  empty,
  showAll,
}: RunsSectionProps) {
  return (
    <Flex direction="column" gap="2">
      <Flex direction="column" gap="0.5" className="cursor-default select-none">
        <Flex align="center" gap="2">
          <Text className="font-semibold text-[13px] text-gray-12">
            {title}
          </Text>
          {count > 0 && (
            <Text className="text-[12px] text-gray-10 tabular-nums">
              {count}
            </Text>
          )}
          {isLive && count > 0 && (
            <span
              className="inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-(--blue-9)"
              aria-hidden
            />
          )}
        </Flex>
        {description && (
          <Text className="text-[12px] text-gray-11 leading-snug">
            {description}
          </Text>
        )}
      </Flex>
      {runs.length === 0 && empty ? (
        <Flex
          align="center"
          gap="3"
          className="cursor-default select-none rounded-(--radius-2) border border-(--gray-5) border-dashed bg-(--gray-1) px-4 py-3.5"
        >
          <Flex
            align="center"
            justify="center"
            className="h-8 w-8 shrink-0 rounded-full bg-(--gray-3) ring-(--gray-5) ring-1 ring-inset"
          >
            <RobotIcon size={14} className="text-gray-10" />
          </Flex>
          <Flex direction="column" gap="0.5" className="min-w-0 flex-1">
            <Text className="font-medium text-[13px] text-gray-12">
              {empty.title}
            </Text>
            <Text className="text-[12px] text-gray-10 leading-snug">
              {empty.description}
            </Text>
          </Flex>
        </Flex>
      ) : (
        <Flex direction="column" gap="3">
          {runs.map((report) => (
            <AgentRunCard key={report.id} report={report} />
          ))}
        </Flex>
      )}
      {showAll && (
        <button
          type="button"
          onClick={showAll.onClick}
          className="self-start rounded-(--radius-1) px-1.5 py-1 font-medium text-[12px] text-accent-11 hover:bg-accent-3 hover:text-accent-12"
        >
          {showAll.kind === "collapse"
            ? "Show less"
            : `Show all ${showAll.hiddenCount} more`}
        </button>
      )}
    </Flex>
  );
}
