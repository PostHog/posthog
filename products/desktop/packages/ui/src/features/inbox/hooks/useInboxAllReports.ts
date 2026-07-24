import {
  buildPriorityFilterParam,
  buildSignalReportListOrdering,
  buildSuggestedReviewerFilterParam,
  filterReportsBySearch,
  INBOX_PIPELINE_STATUS_FILTER,
  INBOX_PULL_REQUEST_STATUS_FILTER,
  INBOX_REFETCH_INTERVAL_MS,
} from "@posthog/core/inbox/reportFiltering";
import {
  INBOX_SCOPE_FOR_YOU,
  isExcludedFromInbox,
  isPullRequestReport,
  isReportTabReport,
  parseTeammateInboxScope,
} from "@posthog/core/inbox/reportMembership";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  useInboxReports,
  useInboxReportsInfinite,
} from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { useMemo } from "react";

// Module-level stable references — selectors returning these never trigger a
// re-render on store updates (Object.is comparison).
const EMPTY_FILTER_ARRAY: never[] = [];

/**
 * `ignoreScope` skips the For-you / Entire-project filter on the returned
 * list. `ignoreFilters` skips the user's source/priority/search/ordering
 * choices and hard-pins ordering to newest-first. Both are used by the
 * Runs tab, where the agent's work is project-wide and the cross-tab
 * filter chrome doesn't meaningfully apply.
 *
 * When `ignoreFilters` is set, the filter-store selectors return constant
 * values so unrelated filter changes don't re-render the consumer.
 */
export function useInboxAllReports(options?: {
  ignoreScope?: boolean;
  ignoreFilters?: boolean;
  pullRequestsOnly?: boolean;
  refetchIntervalMs?: number;
}) {
  const ignoreScope = options?.ignoreScope ?? false;
  const ignoreFilters = options?.ignoreFilters ?? false;
  const refetchIntervalMs =
    options?.refetchIntervalMs ?? INBOX_REFETCH_INTERVAL_MS;
  // The Pull requests tab fetches a server-filtered list (reports that have a
  // shipped PR) so its list body comes from the same source as its count — a PR
  // sitting past the broad list's first page no longer renders an empty tab
  // under a positive badge.
  const pullRequestsOnly = options?.pullRequestsOnly ?? false;
  const scope = useInboxReviewerScopeStore((s) => s.scope);
  const searchQuery = useInboxSignalsFilterStore((s) =>
    ignoreFilters ? "" : s.searchQuery,
  );
  const sortField = useInboxSignalsFilterStore((s) =>
    ignoreFilters ? "updated_at" : s.sortField,
  );
  const sortDirection = useInboxSignalsFilterStore((s) =>
    ignoreFilters ? "desc" : s.sortDirection,
  );
  const sourceProductFilter = useInboxSignalsFilterStore((s) =>
    ignoreFilters ? EMPTY_FILTER_ARRAY : s.sourceProductFilter,
  );
  const priorityFilter = useInboxSignalsFilterStore((s) =>
    ignoreFilters ? EMPTY_FILTER_ARRAY : s.priorityFilter,
  );
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });

  // Reviewer scope is applied server-side via `suggested_reviewers`: "For you"
  // filters on the current user, a teammate scope on theirs, "Entire project"
  // and the Runs tab (`ignoreScope`) send nothing.
  const isForYou = !ignoreScope && scope === INBOX_SCOPE_FOR_YOU;
  const teammateUuid = ignoreScope ? null : parseTeammateInboxScope(scope);
  const reviewerUuid =
    teammateUuid ?? (isForYou ? (currentUser?.uuid ?? null) : null);

  const query = useInboxReportsInfinite(
    {
      // The Pull requests tab shows only `ready` PRs (active review work),
      // matching its count query and the PostHog Cloud inbox.
      status: pullRequestsOnly
        ? INBOX_PULL_REQUEST_STATUS_FILTER
        : INBOX_PIPELINE_STATUS_FILTER,
      has_implementation_pr: pullRequestsOnly ? true : undefined,
      ordering: buildSignalReportListOrdering(sortField, sortDirection),
      source_product:
        sourceProductFilter.length > 0
          ? sourceProductFilter.join(",")
          : undefined,
      priority: buildPriorityFilterParam(priorityFilter),
      suggested_reviewers: reviewerUuid
        ? buildSuggestedReviewerFilterParam([reviewerUuid])
        : undefined,
    },
    {
      // "For you" must always carry the current user's `suggested_reviewers`
      // filter, so hold the query until that uuid resolves rather than firing a
      // throwaway project-wide fetch first. Other scopes don't depend on the
      // user and run immediately.
      enabled: !isForYou || reviewerUuid != null,
      refetchInterval: refetchIntervalMs,
      refetchIntervalInBackground: false,
    },
  );

  // True count of pull-request reports for the active scope. The infinite list
  // only holds the first page(s), so deriving pulls from loaded reports caps at
  // the page size and depends on ordering (a PR can sit past page 1). A cheap
  // `limit: 1` count query with the server-side `has_implementation_pr` filter
  // returns the real total regardless of page size.
  const pullRequestCountQuery = useInboxReports(
    {
      status: INBOX_PULL_REQUEST_STATUS_FILTER,
      has_implementation_pr: true,
      // Mirror the list query's active filters so the badge matches the tab
      // body. These are empty when `ignoreFilters` is set (sidebar usage), so
      // the count stays scope-only there.
      source_product:
        sourceProductFilter.length > 0
          ? sourceProductFilter.join(",")
          : undefined,
      priority: buildPriorityFilterParam(priorityFilter),
      suggested_reviewers: reviewerUuid
        ? buildSuggestedReviewerFilterParam([reviewerUuid])
        : undefined,
      limit: 1,
    },
    {
      enabled: !isForYou || reviewerUuid != null,
      refetchInterval: refetchIntervalMs,
      refetchIntervalInBackground: false,
    },
  );
  const pullRequestTotal = pullRequestCountQuery.data?.count ?? 0;

  const scopedReports = useMemo(() => {
    // Reviewer scope is already applied server-side via `suggested_reviewers`.
    // Don't re-filter on the `is_suggested_reviewer` boolean — it can disagree
    // with that filter, dropping reports the count badge still counts.
    return searchQuery.trim()
      ? filterReportsBySearch(query.allReports, searchQuery)
      : query.allReports;
  }, [query.allReports, searchQuery]);

  const counts = useMemo(() => {
    // Derive Reports from the backend total (the loaded list caps at the page
    // size), subtracting PRs and the other non-report items the total includes.
    // Scope is server-side, so no client reviewer recheck here either.
    const loadedOtherNonReport = query.allReports.filter(
      (r) =>
        !isExcludedFromInbox(r) &&
        !isReportTabReport(r) &&
        !isPullRequestReport(r),
    ).length;
    return {
      // True backend counts, unaffected by the list's page-size cap.
      pulls: pullRequestTotal,
      reports: Math.max(
        0,
        query.totalCount - pullRequestTotal - loadedOtherNonReport,
      ),
    };
  }, [query.allReports, query.totalCount, pullRequestTotal]);

  return {
    ...query,
    scopedReports,
    counts,
    scope,
    // The effective filter values used for this query. Surfaced so consumers
    // (e.g. analytics) can read them without subscribing to the filter store a
    // second time. Reflect `ignoreFilters`, so they are empty when filters are
    // ignored.
    searchQuery,
    sourceProductFilter,
    priorityFilter,
  };
}
