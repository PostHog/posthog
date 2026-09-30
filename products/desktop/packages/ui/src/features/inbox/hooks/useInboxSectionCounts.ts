import {
  buildInboxScopeParams,
  buildPriorityFilterParam,
  INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
  INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { usePersonalInboxEnabled } from "@posthog/ui/features/feature-flags/usePersonalInboxEnabled";
import { useInboxReports } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";

export interface InboxSectionCounts {
  reviewAndMerge: number;
  needsPr: number;
  resolved: number;
  dismissed: number;
  isLoading: boolean;
}

/**
 * Server-side counts for the inbox's sections and badges.
 *
 * Loaded pages only contain a window of the inbox, so each number uses a
 * count-only query with the same server-side filters as its section.
 *
 * Scope and the priority filter are mirrored into every query so the counts
 * move with what the list shows. Search is a client-side title match, so
 * surfaces showing searched rows must count those rows instead.
 */
export function useInboxSectionCounts(): InboxSectionCounts {
  const scope = useInboxReviewerScopeStore((s) => s.scope);
  const priorityFilter = useInboxSignalsFilterStore((s) => s.priorityFilter);
  const personalInboxEnabled = usePersonalInboxEnabled();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });

  const { params: scopeParams, ready: scopeReady } = buildInboxScopeParams({
    scope,
    personalInboxEnabled,
    currentUserUuid: currentUser?.uuid ?? null,
  });
  const shared = {
    priority: buildPriorityFilterParam(priorityFilter),
    ...scopeParams,
    count_only: true,
  };
  const options = {
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  };

  const reviewAndMergeQuery = useInboxReports(
    { ...shared, status: "ready", has_implementation_pr: true },
    { ...options, enabled: scopeReady },
  );
  const needsPrQuery = useInboxReports(
    {
      ...shared,
      status: INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
      actionability: INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
      has_implementation_pr: false,
    },
    { ...options, enabled: scopeReady },
  );
  const resolvedQuery = useInboxReports(
    {
      ...shared,
      status: "resolved",
    },
    { ...options, enabled: scopeReady },
  );
  const dismissedQuery = useInboxReports(
    {
      ...shared,
      status: "suppressed",
    },
    { ...options, enabled: scopeReady },
  );

  return {
    reviewAndMerge: reviewAndMergeQuery.data?.count ?? 0,
    needsPr: needsPrQuery.data?.count ?? 0,
    resolved: resolvedQuery.data?.count ?? 0,
    dismissed: dismissedQuery.data?.count ?? 0,
    isLoading:
      reviewAndMergeQuery.isLoading ||
      needsPrQuery.isLoading ||
      resolvedQuery.isLoading ||
      dismissedQuery.isLoading ||
      !scopeReady,
  };
}
