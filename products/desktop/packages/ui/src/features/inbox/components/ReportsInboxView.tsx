import { INBOX_ACTIONABLE_REPORT_STATUS_FILTER } from "@posthog/core/inbox/reportFiltering";
import { partitionInboxReports } from "@posthog/core/inbox/reportInboxSections";
import { inboxReviewerScopeValue } from "@posthog/core/inbox/reportMembership";
import { useTriageFocusEnabled } from "@posthog/ui/features/feature-flags/useTriageFocusEnabled";
import { InboxReportFilters } from "@posthog/ui/features/inbox/components/InboxReportFilters";
import { InboxReportRow } from "@posthog/ui/features/inbox/components/InboxReportRow";
import { InboxScopeSelect } from "@posthog/ui/features/inbox/components/InboxScopeSelect";
import { ReportsInboxViewPresentation } from "@posthog/ui/features/inbox/components/ReportsInboxViewPresentation";
import { ReportTriageFocus } from "@posthog/ui/features/inbox/components/ReportTriageFocus";
import { ResolvedReportsSection } from "@posthog/ui/features/inbox/components/ResolvedReportsSection";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { useInboxTriageOrigin } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { useInboxSectionCounts } from "@posthog/ui/features/inbox/hooks/useInboxSectionCounts";
import { useTrackReportsInboxViewed } from "@posthog/ui/features/inbox/hooks/useTrackReportsInboxViewed";
import {
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
  const {
    scopedReports,
    allReports,
    isLoading,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    searchQuery,
    scope,
    isSuccess,
    sourceProductFilter,
    priorityFilter,
  } = useInboxAllReports({
    statusFilter: INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
    applySourceFilter: false,
    applySearchFilter: false,
  });
  const triageFocusEnabled = useTriageFocusEnabled();
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

  const sections = useMemo(
    () => partitionInboxReports(scopedReports),
    [scopedReports],
  );
  const serverCounts = useInboxSectionCounts();
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
  const reviewAndMergeCount = showReviewAndMerge
    ? serverCounts.reviewAndMerge
    : 0;
  const needsPrCount = showNeedsDecision ? serverCounts.needsPr : 0;
  const triageReports = useMemo(
    () => [
      ...(showReviewAndMerge ? sections.reviewAndMerge : []),
      ...(showNeedsDecision ? sections.needsPr : []),
    ],
    [
      sections.reviewAndMerge,
      sections.needsPr,
      showNeedsDecision,
      showReviewAndMerge,
    ],
  );

  useTrackReportsInboxViewed({
    reports: triageReports,
    totalCount: reviewAndMergeCount + needsPrCount,
    isReady: isSuccess && !serverCounts.isLoading,
    sourceProductFilter,
    priorityFilter,
    searchQuery,
    scope: inboxReviewerScopeValue(scope),
  });

  useEffect(() => {
    if (
      !hasNextPage ||
      isFetchingNextPage ||
      isLoading ||
      allReports.length >= AUTOPAGE_REPORT_LIMIT
    ) {
      return;
    }
    fetchNextPage();
  }, [
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    allReports.length,
    fetchNextPage,
  ]);

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

  const terminalCount =
    (showResolved ? serverCounts.resolved : 0) +
    (showDismissed ? serverCounts.dismissed : 0);
  const isEmpty =
    !serverCounts.isLoading &&
    reviewAndMergeCount === 0 &&
    needsPrCount === 0 &&
    terminalCount === 0;

  return (
    <ReportsInboxViewPresentation
      reviewAndMerge={sections.reviewAndMerge}
      reviewAndMergeCount={reviewAndMergeCount}
      showReviewAndMerge={showReviewAndMerge}
      needsPr={sections.needsPr}
      needsPrCount={needsPrCount}
      showNeedsDecision={showNeedsDecision}
      isLoading={isLoading}
      isFetchingNextPage={isFetchingNextPage}
      isEmpty={isEmpty}
      hasActiveFilters={hasActiveFilters}
      triageEnabled={triageFocusEnabled}
      filterControl={<InboxReportFilters />}
      scopeControl={<InboxScopeSelect />}
      resolvedSection={
        !isEmpty && (showResolved || showDismissed) ? (
          <ResolvedReportsSection
            searchQuery={searchQuery}
            statuses={[
              ...(showResolved ? (["resolved"] as const) : []),
              ...(showDismissed ? (["suppressed"] as const) : []),
            ]}
            count={terminalCount}
          />
        ) : undefined
      }
      renderReport={(report) => (
        <InboxReportRow key={report.id} report={report} />
      )}
      onConfigureAgents={navigateToAgents}
      onEnterTriage={() => setFocusMode(true)}
      onClearFilters={resetFilters}
    />
  );
}
