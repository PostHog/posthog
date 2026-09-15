import {
  buildStatusFilterParam,
  INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
  INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
  sortInboxReports,
} from "@posthog/core/inbox/reportFiltering";
import type { InboxScope } from "@posthog/core/inbox/reportMembership";
import type {
  SignalReport,
  SignalReportPriority,
  SignalReportStatus,
  SourceProduct,
} from "@posthog/shared/types";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import {
  type InboxReportStateFilter,
  useInboxSignalsFilterStore,
} from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { useEffect, useMemo } from "react";

const AUTOPAGE_REPORT_LIMIT = 400;

/** Stable identity, so a section that is off does not churn its consumers. */
const EMPTY_REPORTS: SignalReport[] = [];

type InboxQuery = ReturnType<typeof useInboxAllReports>;

const SECTION_QUERY_DEFAULTS = {
  applySourceFilter: false,
  applySearchFilter: false,
  groupByStatus: false,
  withPullRequestCount: false,
} as const;

export interface InboxSectionedReports {
  reports: SignalReport[];
  /** The subset triage steps through: reports that still need a decision. */
  triageReports: SignalReport[];
  triageReportCount: number;
  reportCount: number;
  isLoading: boolean;
  isSuccess: boolean;
  isError: boolean;
  isEmpty: boolean;
  isFetchingNextPage: boolean;
  hasNextPage: boolean;
  loadMore: () => void;
  retry: () => void;
  scope: InboxScope;
  reportStateFilter: InboxReportStateFilter[];
  searchQuery: string;
  sourceProductFilter: SourceProduct[];
  priorityFilter: SignalReportPriority[];
}

function useAutoPage(query: InboxQuery, enabled: boolean): void {
  const shouldPage =
    enabled &&
    query.hasNextPage &&
    !query.isFetchingNextPage &&
    !query.isLoading &&
    query.allReports.length < AUTOPAGE_REPORT_LIMIT;
  const { fetchNextPage } = query;

  useEffect(() => {
    if (shouldPage) void fetchNextPage();
  }, [shouldPage, fetchNextPage]);
}

/**
 * Both surfaces that draw the inbox list read it from here, so they cannot
 * disagree about what is in it. React Query dedupes the requests, but paging is
 * a side effect, so only one caller may drive it (`autoPage`).
 */
export function useInboxSectionedReports(options?: {
  autoPage?: boolean;
}): InboxSectionedReports {
  const autoPage = options?.autoPage ?? true;
  const reportStateFilter = useInboxSignalsFilterStore(
    (state) => state.reportStateFilter,
  );
  // Straight from the store, where the type is already the set
  // `sortInboxReports` accepts. The query hook widens it for its own archive
  // mode, which this list never asks for.
  const sortField = useInboxSignalsFilterStore((state) => state.sortField);
  const sortDirection = useInboxSignalsFilterStore(
    (state) => state.sortDirection,
  );

  const showAllStates = reportStateFilter.length === 0;
  const showReviewAndMerge =
    showAllStates || reportStateFilter.includes("review_and_merge");
  const showNeedsDecision =
    showAllStates || reportStateFilter.includes("needs_decision");
  const showTerminal =
    showAllStates ||
    reportStateFilter.includes("resolved") ||
    reportStateFilter.includes("dismissed");
  const terminalStatusFilter = useMemo(() => {
    const statuses: SignalReportStatus[] = [];
    if (showAllStates || reportStateFilter.includes("resolved")) {
      statuses.push("resolved");
    }
    if (showAllStates || reportStateFilter.includes("dismissed")) {
      statuses.push("suppressed");
    }
    return buildStatusFilterParam(statuses);
  }, [reportStateFilter, showAllStates]);

  const reviewAndMergeQuery = useInboxAllReports({
    ...SECTION_QUERY_DEFAULTS,
    enabled: showReviewAndMerge,
    statusFilter: "ready",
    hasImplementationPr: true,
  });
  const needsDecisionQuery = useInboxAllReports({
    ...SECTION_QUERY_DEFAULTS,
    enabled: showNeedsDecision,
    statusFilter: INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
    actionabilityFilter: INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
    hasImplementationPr: false,
  });
  const terminalQuery = useInboxAllReports({
    ...SECTION_QUERY_DEFAULTS,
    enabled: showTerminal,
    statusFilter: terminalStatusFilter,
  });

  useAutoPage(reviewAndMergeQuery, autoPage && showReviewAndMerge);
  useAutoPage(needsDecisionQuery, autoPage && showNeedsDecision);
  useAutoPage(terminalQuery, autoPage && showTerminal);

  const { searchQuery, scope, sourceProductFilter, priorityFilter } =
    reviewAndMergeQuery;
  const triageReports = showNeedsDecision
    ? needsDecisionQuery.scopedReports
    : EMPTY_REPORTS;

  const visibleReports = useMemo(() => {
    const reports = [
      ...(showReviewAndMerge ? reviewAndMergeQuery.scopedReports : []),
      ...(showNeedsDecision ? needsDecisionQuery.scopedReports : []),
      ...(showTerminal ? terminalQuery.scopedReports : []),
    ];
    return sortInboxReports(
      Array.from(
        new Map(reports.map((report) => [report.id, report])).values(),
      ),
      sortField,
      sortDirection,
    );
  }, [
    needsDecisionQuery.scopedReports,
    reviewAndMergeQuery.scopedReports,
    showNeedsDecision,
    showReviewAndMerge,
    showTerminal,
    sortDirection,
    sortField,
    terminalQuery.scopedReports,
  ]);

  const selected = [
    ...(showReviewAndMerge ? [reviewAndMergeQuery] : []),
    ...(showNeedsDecision ? [needsDecisionQuery] : []),
    ...(showTerminal ? [terminalQuery] : []),
  ];
  const reportCount = selected.reduce(
    (total, query) => total + query.totalCount,
    0,
  );
  const isSuccess = selected.every((query) => query.isSuccess);

  return {
    reports: visibleReports,
    triageReports,
    triageReportCount: showNeedsDecision ? needsDecisionQuery.totalCount : 0,
    reportCount,
    isLoading: selected.some((query) => query.isPending),
    isSuccess,
    isError:
      visibleReports.length === 0 && selected.some((query) => query.isError),
    isEmpty: isSuccess && reportCount === 0,
    isFetchingNextPage: selected.some((query) => query.isFetchingNextPage),
    hasNextPage: selected.some(
      (query) =>
        query.hasNextPage && query.allReports.length >= AUTOPAGE_REPORT_LIMIT,
    ),
    loadMore: () => {
      for (const query of selected) {
        if (query.hasNextPage && !query.isFetchingNextPage) {
          void query.fetchNextPage();
        }
      }
    },
    retry: () => {
      if (selected.some((query) => query.isFetching)) return;
      for (const query of selected) void query.refetch();
    },
    scope,
    reportStateFilter,
    searchQuery,
    sourceProductFilter,
    priorityFilter,
  };
}
