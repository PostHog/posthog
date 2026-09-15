import { filterReportsBySearch } from "@posthog/core/inbox/reportFiltering";
import type { SignalReport } from "@posthog/shared/types";
import { InboxFilterMenu } from "@posthog/ui/features/inbox/components/InboxFilterMenu";
import { InboxPanePresentation } from "@posthog/ui/features/inbox/components/InboxPanePresentation";
import { InboxPaneRow } from "@posthog/ui/features/inbox/components/InboxPaneRow";
import { InboxTriageButton } from "@posthog/ui/features/inbox/components/InboxTriageButton";
import { useInboxSectionedReports } from "@posthog/ui/features/inbox/hooks/useInboxSectionedReports";
import {
  hasActiveReportsListFilters,
  useInboxSignalsFilterStore,
} from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { reportIdFromHref } from "@posthog/ui/router/reportNavigation";
import { useRouterState } from "@tanstack/react-router";
import { type ReactElement, useMemo, useState } from "react";

interface InboxPaneProps {
  className?: string;
  onReportActivate?: (report: SignalReport) => void;
}

/**
 * Self-driving's column beside the rail. The list is the navigation, so it
 * stays put while you move between the reports it opens.
 */
export function InboxPane({
  className,
  onReportActivate,
}: InboxPaneProps): ReactElement {
  const inbox = useInboxSectionedReports();
  const [query, setQuery] = useState("");
  const hasActiveFilters = useInboxSignalsFilterStore(
    hasActiveReportsListFilters,
  );
  const resetFilters = useInboxSignalsFilterStore(
    (state) => state.resetFilters,
  );
  const oldestFirst = useInboxSignalsFilterStore(
    (state) =>
      state.sortField === "created_at" && state.sortDirection === "asc",
  );
  // The report being read, taken from the location so the row stays marked
  // across a reload or a restored tab.
  const selectedReportId = useRouterState({
    select: (state) =>
      reportIdFromHref((state.resolvedLocation ?? state.location).pathname),
  });

  const reports = useMemo(
    () => filterReportsBySearch(inbox.reports, query),
    [inbox.reports, query],
  );

  return (
    <InboxPanePresentation
      className={className}
      reports={reports}
      query={query}
      onQueryChange={setQuery}
      isLoading={inbox.isLoading}
      isFetchingNextPage={inbox.isFetchingNextPage}
      hasNextPage={inbox.hasNextPage}
      hasActiveFilters={hasActiveFilters}
      oldestFirst={oldestFirst}
      filterControl={
        <>
          <InboxTriageButton triageReportCount={inbox.triageReports.length} />
          <InboxFilterMenu
            active={hasActiveFilters}
            onClearFilters={resetFilters}
          />
        </>
      }
      renderReport={(report) => (
        <InboxPaneRow
          key={report.id}
          report={report}
          optionValue={report.id}
          isSelected={report.id === selectedReportId}
          onActivate={onReportActivate}
        />
      )}
      onClearFilters={resetFilters}
      onLoadMore={inbox.loadMore}
    />
  );
}
