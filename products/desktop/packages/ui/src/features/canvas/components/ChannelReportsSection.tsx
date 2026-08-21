import { FileMagnifyingGlassIcon } from "@phosphor-icons/react";
import type { ReportChannelView } from "@posthog/core/inbox/reportChannelScope";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Skeleton,
  Spinner,
} from "@posthog/quill";
import { ReportFilterControls } from "@posthog/ui/features/canvas/components/ReportFilterControls";
import { ReportRow } from "@posthog/ui/features/canvas/components/ReportRow";
import {
  type ChannelReportsFilters,
  EMPTY_CHANNEL_REPORTS_FILTERS,
  useChannelReports,
} from "@posthog/ui/features/canvas/hooks/useChannelReports";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
import { useEffect, useMemo, useState } from "react";

/**
 * A space's Reports list. The general space shows every report; any other space
 * shows only reports assigned to it. Search, priority, and a "for you" toggle
 * narrow the list; clicking a row opens the report detail (the sidebar stays
 * mounted, so the list is still there when you come back).
 */
export function ChannelReportsSection({
  view,
  activeReportId,
}: {
  view: ReportChannelView;
  activeReportId: string | null;
}) {
  const [filters, setFilters] = useState<ChannelReportsFilters>(
    EMPTY_CHANNEL_REPORTS_FILTERS,
  );
  const openReport = useOpenInboxReport();
  const {
    reports,
    isLoading,
    isError,
    markSeen,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useChannelReports(view, filters);

  // Infinite scroll: a sentinel below the rows fetches the next page as it
  // nears the viewport. It sits outside the filtered list on purpose — when
  // client-side filters hide a whole page, the sentinel stays visible and
  // keeps paging until a match shows up or the server runs out.
  const [sentinelRef, sentinelInView] = useInView<HTMLDivElement>({
    rootMargin: "600px 0px",
  });
  useEffect(() => {
    if (!sentinelInView || !hasNextPage || isFetchingNextPage || isLoading) {
      return;
    }
    fetchNextPage();
  }, [
    sentinelInView,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    fetchNextPage,
  ]);

  // Looking at the list reads this space's reports; markSeen's identity
  // advances with the newest arrival, so new reports re-stamp while open.
  useEffect(() => {
    markSeen();
  }, [markSeen]);

  const filtersActive =
    filters.relevantToMeOnly || filters.priorities.length > 0;

  const body = useMemo(() => {
    if (isLoading) {
      return (
        <div aria-hidden className="flex flex-col gap-px px-2 pt-1">
          {[60, 80, 45, 70].map((width) => (
            <div key={width} className="flex items-center gap-2 py-1.5">
              <Skeleton className="size-6 shrink-0 rounded" />
              <Skeleton className="h-3.5" style={{ width: `${width}%` }} />
            </div>
          ))}
        </div>
      );
    }
    if (isError) {
      return (
        <Empty className="border-0 py-6">
          <EmptyHeader>
            <EmptyTitle>Couldn't load reports</EmptyTitle>
            <EmptyDescription>
              Check your connection and retry.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      );
    }
    if (reports.length === 0) {
      return (
        <Empty className="border-0 py-6">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FileMagnifyingGlassIcon size={18} />
            </EmptyMedia>
            <EmptyTitle>
              {filtersActive || filters.search
                ? "No matching reports"
                : "No reports yet"}
            </EmptyTitle>
            <EmptyDescription>
              {filtersActive || filters.search
                ? "Try a different search or clear the filters."
                : "Reports your agents file show up here."}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      );
    }
    return (
      <div className="flex flex-col gap-px px-2 pt-1 pb-2">
        {reports.map((report) => (
          <ReportRow
            key={report.id}
            report={report}
            isActive={report.id === activeReportId}
            onOpen={openReport}
          />
        ))}
      </div>
    );
  }, [
    isLoading,
    isError,
    reports,
    activeReportId,
    openReport,
    filtersActive,
    filters.search,
  ]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-1 px-2 pt-1 pb-1">
        <ReportFilterControls filters={filters} onChange={setFilters} />
      </div>
      <div className="scroll-mask-4 min-h-0 flex-1 overflow-y-auto">
        {body}
        {!isLoading && !isError && (hasNextPage || isFetchingNextPage) && (
          <div
            ref={sentinelRef}
            className="flex items-center justify-center py-2"
          >
            {isFetchingNextPage && <Spinner />}
          </div>
        )}
      </div>
    </div>
  );
}
