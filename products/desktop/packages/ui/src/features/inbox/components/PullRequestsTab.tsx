import { GitPullRequestIcon } from "@phosphor-icons/react";
import { isPullRequestReport } from "@posthog/core/inbox/reportMembership";
import type { SignalReport } from "@posthog/shared/types";
import { InboxReportListTab } from "@posthog/ui/features/inbox/components/InboxReportListTab";
import { PullRequestCard } from "@posthog/ui/features/inbox/components/PullRequestCard";
import {
  PrDiffStatsBatchContext,
  type PrDiffStatsBatchContextValue,
} from "@posthog/ui/features/inbox/context/PrDiffStatsBatchContext";
import { usePrDiffStatsBatch } from "@posthog/ui/features/inbox/hooks/usePrDiffStatsBatch";
import { type ReactNode, useMemo } from "react";

export function PullRequestsTab() {
  return (
    <InboxReportListTab
      predicate={isPullRequestReport}
      pullRequestsOnly
      Card={PullRequestCard}
      CardListWrapper={PullRequestsBatchProvider}
      searchPlaceholder="Search pull requests…"
      emptyState={{
        Icon: GitPullRequestIcon,
        forYouTitle: "No pull requests for you right now",
        entireProjectTitle: "No pull requests in the project right now",
        teammateTitle: "No pull requests for this reviewer right now",
        description:
          "When a Responder ships a code change, the PR draft lands here for you to review and publish.",
      }}
    />
  );
}

/**
 * Fetches diff stats for every visible PR URL in one batched GraphQL request
 * and exposes them via context. `PullRequestCard` reads from the context
 * through `usePrDiffStatsFromBatch`; the per-PR REST query is only used on
 * the standalone detail view.
 */
function PullRequestsBatchProvider({
  reports,
  children,
}: {
  reports: SignalReport[];
  children: ReactNode;
}) {
  const prUrls = useMemo(
    () =>
      reports
        .map((report) => report.implementation_pr_url)
        .filter((url): url is string => !!url),
    [reports],
  );

  const { data: batch, isLoading } = usePrDiffStatsBatch(prUrls);

  const value = useMemo<PrDiffStatsBatchContextValue>(
    () => ({ batch, isLoading, hasBatch: true }),
    [batch, isLoading],
  );

  return (
    <PrDiffStatsBatchContext.Provider value={value}>
      {children}
    </PrDiffStatsBatchContext.Provider>
  );
}
