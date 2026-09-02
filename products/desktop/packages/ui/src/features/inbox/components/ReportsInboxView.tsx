import {
  buildStatusFilterParam,
  INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
  INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
  sortInboxReports,
} from "@posthog/core/inbox/reportFiltering";
import { inboxReviewerScopeValue } from "@posthog/core/inbox/reportMembership";
import type { SignalReportStatus } from "@posthog/shared/types";
import { useTriageFocusEnabled } from "@posthog/ui/features/feature-flags/useTriageFocusEnabled";
import { InboxReportFilters } from "@posthog/ui/features/inbox/components/InboxReportFilters";
import { InboxReportRow } from "@posthog/ui/features/inbox/components/InboxReportRow";
import { InboxScopeSelect } from "@posthog/ui/features/inbox/components/InboxScopeSelect";
import { ReportsInboxViewPresentation } from "@posthog/ui/features/inbox/components/ReportsInboxViewPresentation";
import { ReportTriageFocus } from "@posthog/ui/features/inbox/components/ReportTriageFocus";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { useInboxTriageOrigin } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { useSignalSourceConfigs } from "@posthog/ui/features/inbox/hooks/useSignalSourceConfigs";
import { useTrackReportsInboxViewed } from "@posthog/ui/features/inbox/hooks/useTrackReportsInboxViewed";
import {
  DEFAULT_INBOX_REPORT_STATE_FILTER,
  hasActiveInboxFilters,
  useInboxSignalsFilterStore,
} from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { navigateToAgents } from "@posthog/ui/router/navigationBridge";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  );
}

const AUTOPAGE_REPORT_LIMIT = 400;

export function ReportsInboxView(): React.JSX.Element {
  const reportStateFilter = useInboxSignalsFilterStore(
    (state) => state.reportStateFilter,
  );
  const showAllStates = reportStateFilter.length === 0;
  const showReviewAndMerge =
    showAllStates || reportStateFilter.includes("review_and_merge");
  const showNeedsDecision =
    showAllStates || reportStateFilter.includes("needs_decision");
  const showResolved = showAllStates || reportStateFilter.includes("resolved");
  const showDismissed =
    showAllStates || reportStateFilter.includes("dismissed");
  const terminalStatusFilter = useMemo(() => {
    const statuses: SignalReportStatus[] = [];
    if (showResolved) statuses.push("resolved");
    if (showDismissed) statuses.push("suppressed");
    return buildStatusFilterParam(statuses);
  }, [showDismissed, showResolved]);
  const reviewAndMergeQuery = useInboxAllReports({
    enabled: showReviewAndMerge,
    statusFilter: "ready",
    hasImplementationPr: true,
    applySourceFilter: false,
    applySearchFilter: false,
    groupByStatus: false,
    withPullRequestCount: false,
  });
  const needsDecisionQuery = useInboxAllReports({
    enabled: showNeedsDecision,
    statusFilter: INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
    actionabilityFilter: INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
    hasImplementationPr: false,
    applySourceFilter: false,
    applySearchFilter: false,
    groupByStatus: false,
    withPullRequestCount: false,
  });
  const terminalQuery = useInboxAllReports({
    enabled: showResolved || showDismissed,
    statusFilter: terminalStatusFilter,
    applySourceFilter: false,
    applySearchFilter: false,
    groupByStatus: false,
    withPullRequestCount: false,
  });
  const {
    searchQuery,
    scope,
    sourceProductFilter,
    priorityFilter,
    sortField,
    sortDirection,
  } = reviewAndMergeQuery;
  const triageFocusEnabled = useTriageFocusEnabled();
  const sourceConfigs = useSignalSourceConfigs();
  const triageOrigin = useInboxTriageOrigin();
  const navigate = useNavigate();
  const [focusMode, setFocusMode] = useState(() => triageOrigin !== null);

  const exitFocusMode = useCallback(() => {
    setFocusMode(false);
    if (!triageOrigin) return;
    void navigate({
      to: "/inbox/reports",
      replace: true,
      state: (previous) => ({
        ...previous,
        inboxTriageOrigin: undefined,
      }),
    });
  }, [navigate, triageOrigin]);

  const hasActiveFilters = useInboxSignalsFilterStore((state) =>
    hasActiveInboxFilters(state, {
      includePrFilter: false,
      includeSourceFilter: false,
      includeReportStateFilter: true,
      includeSearchFilter: false,
    }),
  );
  const resetFilters = useInboxSignalsFilterStore(
    (state) => state.resetFilters,
  );
  const reviewAndMergeCount = showReviewAndMerge
    ? reviewAndMergeQuery.totalCount
    : 0;
  const needsPrCount = showNeedsDecision ? needsDecisionQuery.totalCount : 0;
  const triageReports = showNeedsDecision
    ? needsDecisionQuery.scopedReports
    : [];
  const visibleReports = useMemo(() => {
    const reports = [
      ...(showReviewAndMerge ? reviewAndMergeQuery.scopedReports : []),
      ...(showNeedsDecision ? needsDecisionQuery.scopedReports : []),
      ...(showResolved || showDismissed ? terminalQuery.scopedReports : []),
    ];
    return sortInboxReports(
      Array.from(
        new Map(reports.map((report) => [report.id, report])).values(),
      ),
      sortField === "priority" ||
        sortField === "created_at" ||
        sortField === "total_weight"
        ? sortField
        : "created_at",
      sortDirection,
    );
  }, [
    needsDecisionQuery.scopedReports,
    reviewAndMergeQuery.scopedReports,
    showDismissed,
    showNeedsDecision,
    showResolved,
    showReviewAndMerge,
    sortDirection,
    sortField,
    terminalQuery.scopedReports,
  ]);

  const terminalCount =
    showResolved || showDismissed ? terminalQuery.totalCount : 0;
  const reportCount = reviewAndMergeCount + needsPrCount + terminalCount;
  const selectedQueries = [
    ...(showReviewAndMerge ? [reviewAndMergeQuery] : []),
    ...(showNeedsDecision ? [needsDecisionQuery] : []),
    ...(showResolved || showDismissed ? [terminalQuery] : []),
  ];
  const allReports = visibleReports;
  const isLoading = selectedQueries.some((query) => query.isPending);
  const isSuccess = selectedQueries.every((query) => query.isSuccess);
  const isError =
    visibleReports.length === 0 &&
    selectedQueries.some((query) => query.isError);
  const isFetchingNextPage = selectedQueries.some(
    (query) => query.isFetchingNextPage,
  );
  const hasNextPage = selectedQueries.some(
    (query) =>
      query.hasNextPage && query.allReports.length >= AUTOPAGE_REPORT_LIMIT,
  );

  useTrackReportsInboxViewed({
    reports: visibleReports,
    totalCount: reportCount,
    isReady: isSuccess,
    sourceProductFilter,
    priorityFilter,
    searchQuery,
    scope: inboxReviewerScopeValue(scope),
    reportStateFilter,
    defaultReportStateFilter: DEFAULT_INBOX_REPORT_STATE_FILTER,
  });

  useEffect(() => {
    if (
      !showReviewAndMerge ||
      !reviewAndMergeQuery.hasNextPage ||
      reviewAndMergeQuery.isFetchingNextPage ||
      reviewAndMergeQuery.isLoading ||
      reviewAndMergeQuery.allReports.length >= AUTOPAGE_REPORT_LIMIT
    ) {
      return;
    }
    void reviewAndMergeQuery.fetchNextPage();
  }, [
    reviewAndMergeQuery.allReports.length,
    reviewAndMergeQuery.fetchNextPage,
    reviewAndMergeQuery.hasNextPage,
    reviewAndMergeQuery.isFetchingNextPage,
    reviewAndMergeQuery.isLoading,
    showReviewAndMerge,
  ]);

  useEffect(() => {
    if (
      !showNeedsDecision ||
      !needsDecisionQuery.hasNextPage ||
      needsDecisionQuery.isFetchingNextPage ||
      needsDecisionQuery.isLoading ||
      needsDecisionQuery.allReports.length >= AUTOPAGE_REPORT_LIMIT
    ) {
      return;
    }
    void needsDecisionQuery.fetchNextPage();
  }, [
    needsDecisionQuery.allReports.length,
    needsDecisionQuery.fetchNextPage,
    needsDecisionQuery.hasNextPage,
    needsDecisionQuery.isFetchingNextPage,
    needsDecisionQuery.isLoading,
    showNeedsDecision,
  ]);

  useEffect(() => {
    if (
      (!showResolved && !showDismissed) ||
      !terminalQuery.hasNextPage ||
      terminalQuery.isFetchingNextPage ||
      terminalQuery.isLoading ||
      terminalQuery.allReports.length >= AUTOPAGE_REPORT_LIMIT
    ) {
      return;
    }
    void terminalQuery.fetchNextPage();
  }, [
    showDismissed,
    showResolved,
    terminalQuery.allReports.length,
    terminalQuery.fetchNextPage,
    terminalQuery.hasNextPage,
    terminalQuery.isFetchingNextPage,
    terminalQuery.isLoading,
  ]);

  const loadMore = (): void => {
    for (const query of selectedQueries) {
      if (query.hasNextPage && !query.isFetchingNextPage) {
        void query.fetchNextPage();
      }
    }
  };
  const retry = (): void => {
    for (const query of selectedQueries) void query.refetch();
  };

  useEffect(() => {
    if (!triageFocusEnabled || focusMode) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (isTypingTarget(event.target)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "t" && triageReports.length > 0) {
        event.preventDefault();
        setFocusMode(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [triageFocusEnabled, focusMode, triageReports.length]);

  if (triageFocusEnabled && focusMode && !isLoading) {
    return (
      <div className="h-full min-h-0">
        <ReportTriageFocus
          reports={triageReports}
          allReports={allReports}
          scope={scope}
          hasActiveFilters={hasActiveFilters}
          initialReportId={triageOrigin?.reportId}
          onExit={exitFocusMode}
        />
      </div>
    );
  }

  const isEmpty = isSuccess && reportCount === 0;
  const isAgentConfigurationLoading =
    isEmpty && !hasActiveFilters && sourceConfigs.isPending;
  const showConfigureAgentsEmptyState =
    isEmpty &&
    !hasActiveFilters &&
    sourceConfigs.isSuccess &&
    !sourceConfigs.data?.some((config) => config.enabled);

  return (
    <ReportsInboxViewPresentation
      reports={visibleReports}
      triageReportCount={needsPrCount}
      isLoading={isLoading || isAgentConfigurationLoading}
      isFetchingNextPage={isFetchingNextPage}
      hasNextPage={hasNextPage}
      isError={isError}
      isEmpty={isEmpty}
      hasActiveFilters={hasActiveFilters}
      showConfigureAgentsEmptyState={showConfigureAgentsEmptyState}
      triageEnabled={triageFocusEnabled}
      filterControl={<InboxReportFilters />}
      scopeControl={<InboxScopeSelect />}
      renderReport={(report) => (
        <InboxReportRow key={report.id} report={report} />
      )}
      onConfigureAgents={navigateToAgents}
      onEnterTriage={() => setFocusMode(true)}
      onClearFilters={resetFilters}
      onLoadMore={loadMore}
      onRetry={retry}
    />
  );
}
