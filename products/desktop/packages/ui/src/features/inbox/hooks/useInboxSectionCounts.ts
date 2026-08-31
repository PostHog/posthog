import {
  buildPriorityFilterParam,
  buildSuggestedReviewerFilterParam,
  INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
  INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import {
  INBOX_SCOPE_FOR_YOU,
  parseTeammateInboxScope,
} from "@posthog/core/inbox/reportMembership";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useInboxReports } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";

export interface InboxSectionCounts {
  reviewAndMerge: number;
  needsPr: number;
  resolved: number;
  isLoading: boolean;
}

/**
 * Server-side counts for the inbox's sections and badges.
 *
 * At this dataset's real size (tens of thousands of live reports in a shared
 * project) any count derived from loaded pages is a count of a window, not of
 * reality — which is where every badge/section mismatch came from. So each
 * number here is a count-only query on the dimensions the API can filter
 * server-side (status, actionability, PR presence, reviewer scope, source,
 * priority), and the sections are deliberately defined on those dimensions.
 *
 * Scope and the filter bar's source/priority choices are mirrored into every
 * query so the counts move with what the list shows. Search is not — it's a
 * client-side title match, so surfaces showing searched rows must count those
 * rows instead.
 */
export function useInboxSectionCounts(): InboxSectionCounts {
  const scope = useInboxReviewerScopeStore((s) => s.scope);
  const sourceProductFilter = useInboxSignalsFilterStore(
    (s) => s.sourceProductFilter,
  );
  const priorityFilter = useInboxSignalsFilterStore((s) => s.priorityFilter);
  const prFilter = useInboxSignalsFilterStore((s) => s.prFilter);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });

  const isForYou = scope === INBOX_SCOPE_FOR_YOU;
  const teammateUuid = parseTeammateInboxScope(scope);
  const reviewerUuid =
    teammateUuid ?? (isForYou ? (currentUser?.uuid ?? null) : null);

  const shared = {
    source_product:
      sourceProductFilter.length > 0
        ? sourceProductFilter.join(",")
        : undefined,
    priority: buildPriorityFilterParam(priorityFilter),
    suggested_reviewers: reviewerUuid
      ? buildSuggestedReviewerFilterParam([reviewerUuid])
      : undefined,
    count_only: true,
  };
  const scopeReady = !isForYou || reviewerUuid != null;
  const options = {
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  };

  const reviewAndMergeEnabled = scopeReady && prFilter !== "without_pr";
  const needsPrEnabled = scopeReady && prFilter !== "with_pr";
  const reviewAndMergeQuery = useInboxReports(
    { ...shared, status: "ready", has_implementation_pr: true },
    { ...options, enabled: reviewAndMergeEnabled },
  );
  const needsPrQuery = useInboxReports(
    {
      ...shared,
      status: INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
      actionability: INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
      has_implementation_pr: false,
    },
    { ...options, enabled: needsPrEnabled },
  );
  const resolvedQuery = useInboxReports(
    {
      ...shared,
      status: "suppressed,resolved",
      has_implementation_pr:
        prFilter === "with_pr"
          ? true
          : prFilter === "without_pr"
            ? false
            : undefined,
    },
    { ...options, enabled: scopeReady },
  );

  return {
    reviewAndMerge: reviewAndMergeEnabled
      ? (reviewAndMergeQuery.data?.count ?? 0)
      : 0,
    needsPr: needsPrEnabled ? (needsPrQuery.data?.count ?? 0) : 0,
    resolved: resolvedQuery.data?.count ?? 0,
    isLoading:
      (reviewAndMergeEnabled && reviewAndMergeQuery.isLoading) ||
      (needsPrEnabled && needsPrQuery.isLoading) ||
      resolvedQuery.isLoading ||
      (isForYou && reviewerUuid == null),
  };
}
