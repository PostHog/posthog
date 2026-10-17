import { RobotIcon } from "@phosphor-icons/react";
import {
  INBOX_SCOPE_ENTIRE_PROJECT,
  INBOX_SCOPE_FOR_YOU,
  orderedRunsTabReports,
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
import { useMemo } from "react";

export function RunsTab(): React.JSX.Element {
  // Runs is project-wide and intentionally chrome-less. Reviewer assignment
  // is an output of research, so For-you would silently empty queued / live;
  // source and priority filters don't read as run-shaped questions either.
  // We pin ordering to newest-first locally too.
  const { scopedReports, isLoading } = useInboxAllReports({
    ignoreScope: true,
    ignoreFilters: true,
    groupByStatus: false,
  });
  const scope = useInboxReviewerScopeStore((state) => state.scope);
  const runs = useMemo(
    () => orderedRunsTabReports(scopedReports),
    [scopedReports],
  );

  if (isLoading && scopedReports.length === 0) {
    return (
      <div className="@container mx-auto flex w-full max-w-3xl flex-col gap-4 px-6 py-4">
        <CardSkeleton count={3} variant="rows" />
      </div>
    );
  }

  return (
    <div className="@container mx-auto flex w-full max-w-3xl flex-col gap-4 px-6 py-4">
      {runs.length === 0 ? (
        <Empty className="mx-auto max-w-md py-16">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <RobotIcon size={24} />
            </EmptyMedia>
            <EmptyTitle>
              {scope === INBOX_SCOPE_FOR_YOU
                ? "No agents are working on something for you right now"
                : scope === INBOX_SCOPE_ENTIRE_PROJECT
                  ? "No agents are working on anything in the project right now"
                  : "No agents are working on something for this reviewer right now"}
            </EmptyTitle>
            <EmptyDescription>
              When Self-driving kicks one off, you'll see the live run land here
              until it finishes as a Pull request or a Report.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="flex flex-col gap-3">
          {runs.map((report) => (
            <AgentRunCard key={report.id} report={report} />
          ))}
        </div>
      )}
    </div>
  );
}
