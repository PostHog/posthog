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
import type { SignalReport } from "@posthog/shared/types";
import { ReportRow } from "@posthog/ui/features/canvas/components/ReportRow";
import {
  type ChannelReportsFilters,
  useChannelReports,
} from "@posthog/ui/features/canvas/hooks/useChannelReports";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
import { useEffect, useMemo } from "react";

/**
 * A space's Reports list. The general space shows every report; any other space
 * shows only reports assigned to it. The filters (shared search bar, priority,
 * status, "For you") live in the tab header and arrive as a prop; clicking a
 * row opens the report detail (the sidebar stays mounted, so the list is still
 * there when you come back). Reading happens on open, not on browsing — the
 * unread badge clears in the sidebar's cut-over effect when a report is
 * clicked into.
 */
export function ChannelReportsSection({
  view,
  activeReportId,
  filters,
}: {
  view: ReportChannelView;
  activeReportId: string | null;
  filters: ChannelReportsFilters;
}) {
  const openReport = useOpenInboxReport();
  const {
    reports,
    sections,
    isLoading,
    isError,
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

  const filtersActive =
    filters.relevantToMeOnly ||
    filters.priorities.length > 0 ||
    filters.status !== "all";
  // The default scope, not a user choice — the empty state names it so an
  // empty list isn't mistaken for having no reports at all.
  const onlyForYouActive =
    filters.relevantToMeOnly &&
    !filters.search &&
    filters.priorities.length === 0 &&
    filters.status === "all";

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
              {onlyForYouActive
                ? "No reports for you yet"
                : filtersActive || filters.search
                  ? "No matching reports"
                  : "No reports yet"}
            </EmptyTitle>
            <EmptyDescription>
              {onlyForYouActive
                ? "Showing reports suggested for you. Open the filter to see every report in this space."
                : filtersActive || filters.search
                  ? "Try a different search or clear the filters."
                  : "Reports your agents file show up here."}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      );
    }
    // In the default browse state the most important actionable reports pin
    // above a divider (priority-first); the stream below stays chronological.
    // Any active filter collapses back to one plain list (`needsAttention` is
    // empty then), so this renders both shapes.
    const { needsAttention, rest } = sections;
    const row = (report: SignalReport) => (
      <ReportRow
        key={report.id}
        report={report}
        isActive={report.id === activeReportId}
        onOpen={openReport}
      />
    );
    return (
      <div className="flex flex-col gap-px px-2 pt-1 pb-2">
        {needsAttention.length > 0 && (
          <>
            <div className="px-1.5 pt-1 pb-0.5 font-medium text-(--gray-10) text-[11px]">
              Needs attention
            </div>
            {needsAttention.map(row)}
            {rest.length > 0 && (
              <div
                aria-hidden
                className="mx-1.5 my-1.5 border-(--gray-5) border-t"
              />
            )}
          </>
        )}
        {rest.map(row)}
      </div>
    );
  }, [
    isLoading,
    isError,
    reports,
    sections,
    activeReportId,
    openReport,
    filtersActive,
    onlyForYouActive,
    filters.search,
  ]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
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
