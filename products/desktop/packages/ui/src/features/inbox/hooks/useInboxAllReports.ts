import {
  buildPriorityFilterParam,
  buildSignalReportListOrdering,
  buildSuggestedReviewerFilterParam,
  filterReportsBySearch,
  INBOX_PIPELINE_STATUS_FILTER,
  INBOX_PULL_REQUEST_STATUS_FILTER,
  INBOX_REFETCH_INTERVAL_MS,
  INBOX_REPORTS_TAB_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import {
  INBOX_SCOPE_FOR_YOU,
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
 *
 * `withReportsCount` opts into the extra count query behind `counts.reports`;
 * without it that count stays 0. Only surfaces that render that count should
 * pay for its request.
 */
export function useInboxAllReports(options?: {
  enabled?: boolean;
  ignoreScope?: boolean;
  ignoreFilters?: boolean;
  pullRequestsOnly?: boolean;
  withReportsCount?: boolean;
  refetchIntervalMs?: number;
  /**
   * Overrides the pipeline status set (server-side, part of the query key).
   * Callers sharing one dataset must pass the same value.
   */
  statusFilter?: string;
  /**
   * Apply the persisted `prFilter` (with-PR / without-PR) to the query. Only
   * the sectioned inbox renders the control that sets it, so only it opts in —
   * otherwise a stored value would silently filter surfaces with no way to
   * clear it (e.g. empty the legacy Reports tab, which then drops PR-backed
   * reports itself).
   */
  applyPrFilter?: boolean;
}) {
  const enabled = options?.enabled ?? true;
  const ignoreScope = options?.ignoreScope ?? false;
  const ignoreFilters = options?.ignoreFilters ?? false;
  const applyPrFilter = options?.applyPrFilter ?? false;
  const refetchIntervalMs =
    options?.refetchIntervalMs ?? INBOX_REFETCH_INTERVAL_MS;
  // The Pull requests tab fetches a server-filtered list (reports that have a
  // shipped PR) so its list body comes from the same source as its count — a PR
  // sitting past the broad list's first page no longer renders an empty tab
  // under a positive badge.
  const pullRequestsOnly = options?.pullRequestsOnly ?? false;
  const withReportsCount = options?.withReportsCount ?? false;
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
  const prFilter = useInboxSignalsFilterStore((s) =>
    ignoreFilters || !applyPrFilter ? "all" : s.prFilter,
  );
  const isForYou = !ignoreScope && scope === INBOX_SCOPE_FOR_YOU;
  const teammateUuid = ignoreScope ? null : parseTeammateInboxScope(scope);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({
    client,
    enabled: enabled && isForYou && teammateUuid === null,
  });

  // Reviewer scope is applied server-side via `suggested_reviewers`: "For you"
  // filters on the current user, a teammate scope on theirs, "Entire project"
  // and the Runs tab (`ignoreScope`) send nothing.
  const reviewerUuid =
    teammateUuid ?? (isForYou ? (currentUser?.uuid ?? null) : null);

  const query = useInboxReportsInfinite(
    {
      // The Pull requests tab shows only `ready` PRs (active review work),
      // matching its count query and the PostHog Cloud inbox.
      status: pullRequestsOnly
        ? INBOX_PULL_REQUEST_STATUS_FILTER
        : (options?.statusFilter ?? INBOX_PIPELINE_STATUS_FILTER),
      has_implementation_pr: pullRequestsOnly
        ? true
        : prFilter === "with_pr"
          ? true
          : prFilter === "without_pr"
            ? false
            : undefined,
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
      enabled: enabled && (!isForYou || reviewerUuid != null),
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
      enabled: enabled && (!isForYou || reviewerUuid != null),
      refetchInterval: refetchIntervalMs,
      refetchIntervalInBackground: false,
    },
  );
  const pullRequestTotal = pullRequestCountQuery.data?.count ?? 0;

  // True count of Reports-tab reports for the active scope, on the same
  // `limit: 1` pattern as the pull-request count above. Deriving it instead by
  // subtracting from the pipeline total only works if every non-report item is
  // visible in the loaded pages, and the list is ordered `ready` first, so the
  // queued, live and failed runs sit past page 1 and never get subtracted.
  const reportsCountQuery = useInboxReports(
    {
      status: INBOX_REPORTS_TAB_STATUS_FILTER,
      has_implementation_pr: false,
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
      enabled:
        enabled && withReportsCount && (!isForYou || reviewerUuid != null),
      refetchInterval: refetchIntervalMs,
      refetchIntervalInBackground: false,
    },
  );
  const reportsTotal = reportsCountQuery.data?.count ?? 0;

  const scopedReports = useMemo(() => {
    // Reviewer scope is already applied server-side via `suggested_reviewers`.
    // Don't re-filter on the `is_suggested_reviewer` boolean — it can disagree
    // with that filter, dropping reports the count badge still counts.
    return searchQuery.trim()
      ? filterReportsBySearch(query.allReports, searchQuery)
      : query.allReports;
  }, [query.allReports, searchQuery]);

  // Both are backend counts under the same server-side scope and filters as the
  // list, so they are unaffected by its page-size cap and need no client-side
  // reviewer recheck.
  const counts = useMemo(
    () => ({ pulls: pullRequestTotal, reports: reportsTotal }),
    [pullRequestTotal, reportsTotal],
  );

  // Each count is its own request, so the list can succeed while they are still
  // in flight and `counts` still reads 0. Anything that records the counts once
  // and never revises them has to wait for this rather than for the list.
  const countsReady =
    pullRequestCountQuery.isSuccess &&
    (!withReportsCount || reportsCountQuery.isSuccess);

  return {
    ...query,
    scopedReports,
    counts,
    countsReady,
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
