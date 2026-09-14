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

/**
 * The navigation badge counts the active report groups selected in the Inbox.
 * Keeping it separate from `useInboxSectionCounts` avoids polling terminal
 * section counts on every route.
 */
export function useInboxDecisionCount(options?: { enabled?: boolean }): number {
  const enabled = options?.enabled ?? true;
  const scope = useInboxReviewerScopeStore((state) => state.scope);
  const priorityFilter = useInboxSignalsFilterStore(
    (state) => state.priorityFilter,
  );
  const reportStateFilter = useInboxSignalsFilterStore(
    (state) => state.reportStateFilter,
  );
  const showAllStates = reportStateFilter.length === 0;
  const showReviewAndMerge =
    showAllStates || reportStateFilter.includes("review_and_merge");
  const showNeedsDecision =
    showAllStates || reportStateFilter.includes("needs_decision");
  const shouldCount = enabled && (showReviewAndMerge || showNeedsDecision);
  const isForYou = scope === INBOX_SCOPE_FOR_YOU;
  const teammateUuid = parseTeammateInboxScope(scope);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({
    client,
    enabled: shouldCount && isForYou && teammateUuid === null,
  });
  const reviewerUuid =
    teammateUuid ?? (isForYou ? (currentUser?.uuid ?? null) : null);
  const scopeReady = !isForYou || reviewerUuid !== null;
  const sharedFilters = {
    priority: buildPriorityFilterParam(priorityFilter),
    suggested_reviewers: reviewerUuid
      ? buildSuggestedReviewerFilterParam([reviewerUuid])
      : undefined,
    count_only: true,
  };
  const queryOptions = {
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  };
  const reviewAndMergeQuery = useInboxReports(
    {
      ...sharedFilters,
      status: "ready",
      has_implementation_pr: true,
    },
    {
      ...queryOptions,
      enabled: shouldCount && showReviewAndMerge && scopeReady,
    },
  );
  const needsDecisionQuery = useInboxReports(
    {
      ...sharedFilters,
      status: INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
      actionability: INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
      has_implementation_pr: false,
    },
    {
      ...queryOptions,
      enabled: shouldCount && showNeedsDecision && scopeReady,
    },
  );

  if (!shouldCount) return 0;
  return (
    (reviewAndMergeQuery.data?.count ?? 0) +
    (needsDecisionQuery.data?.count ?? 0)
  );
}
