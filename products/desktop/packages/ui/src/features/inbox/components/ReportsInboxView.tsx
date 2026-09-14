import { inboxReviewerScopeValue } from "@posthog/core/inbox/reportMembership";
import { useTriageFocusEnabled } from "@posthog/ui/features/feature-flags/useTriageFocusEnabled";
import { InboxReportFilters } from "@posthog/ui/features/inbox/components/InboxReportFilters";
import { InboxReportRow } from "@posthog/ui/features/inbox/components/InboxReportRow";
import { InboxScopeSelect } from "@posthog/ui/features/inbox/components/InboxScopeSelect";
import { ReportsInboxViewPresentation } from "@posthog/ui/features/inbox/components/ReportsInboxViewPresentation";
import { useInboxSectionedReports } from "@posthog/ui/features/inbox/hooks/useInboxSectionedReports";
import { useInboxTriageHotkey } from "@posthog/ui/features/inbox/hooks/useInboxTriageHotkey";
import { useSelfDrivingSetupStatus } from "@posthog/ui/features/inbox/hooks/useSelfDrivingSetupStatus";
import { useTrackReportsInboxViewed } from "@posthog/ui/features/inbox/hooks/useTrackReportsInboxViewed";
import {
  DEFAULT_INBOX_REPORT_STATE_FILTER,
  hasActiveReportsListFilters,
  useInboxSignalsFilterStore,
} from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { INBOX_TRIAGE_ROUTE } from "@posthog/ui/features/inbox/triageRoute";
import { navigateToSettings } from "@posthog/ui/router/navigationBridge";
import { useNavigate } from "@tanstack/react-router";

export function ReportsInboxView(): React.JSX.Element {
  const inbox = useInboxSectionedReports();
  const triageEnabled = useTriageFocusEnabled();
  const setupStatus = useSelfDrivingSetupStatus();
  const navigate = useNavigate();
  const hasActiveFilters = useInboxSignalsFilterStore(
    hasActiveReportsListFilters,
  );
  const resetFilters = useInboxSignalsFilterStore(
    (state) => state.resetFilters,
  );

  useInboxTriageHotkey({
    enabled: triageEnabled,
    triageReportCount: inbox.triageReports.length,
  });

  useTrackReportsInboxViewed({
    reports: inbox.reports,
    totalCount: inbox.reportCount,
    isReady: inbox.isSuccess,
    sourceProductFilter: inbox.sourceProductFilter,
    priorityFilter: inbox.priorityFilter,
    searchQuery: inbox.searchQuery,
    scope: inboxReviewerScopeValue(inbox.scope),
    reportStateFilter: inbox.reportStateFilter,
    defaultReportStateFilter: DEFAULT_INBOX_REPORT_STATE_FILTER,
  });

  const isAgentConfigurationLoading =
    inbox.isEmpty && !hasActiveFilters && setupStatus.isLoading;
  const showConfigureAgentsEmptyState =
    inbox.isEmpty &&
    !hasActiveFilters &&
    !setupStatus.isLoading &&
    !setupStatus.isConfigured;

  return (
    <ReportsInboxViewPresentation
      reports={inbox.reports}
      triageReportCount={inbox.triageReportCount}
      isLoading={inbox.isLoading || isAgentConfigurationLoading}
      isFetchingNextPage={inbox.isFetchingNextPage}
      hasNextPage={inbox.hasNextPage}
      isError={inbox.isError}
      isEmpty={inbox.isEmpty}
      hasActiveFilters={hasActiveFilters}
      showConfigureAgentsEmptyState={showConfigureAgentsEmptyState}
      triageEnabled={triageEnabled}
      filterControl={<InboxReportFilters />}
      scopeControl={<InboxScopeSelect />}
      renderReport={(report) => (
        <InboxReportRow key={report.id} report={report} />
      )}
      onConfigureAgents={() => navigateToSettings("agents")}
      onEnterTriage={() => void navigate({ to: INBOX_TRIAGE_ROUTE })}
      onClearFilters={resetFilters}
      onLoadMore={inbox.loadMore}
      onRetry={inbox.retry}
    />
  );
}
