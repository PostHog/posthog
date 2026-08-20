import { FileMagnifyingGlassIcon } from "@phosphor-icons/react";
import type { ReportChannelView } from "@posthog/core/inbox/reportChannelScope";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Skeleton,
} from "@posthog/quill";
import { ReportFilterControls } from "@posthog/ui/features/canvas/components/ReportFilterControls";
import { ReportRow } from "@posthog/ui/features/canvas/components/ReportRow";
import {
  type ChannelReportsFilters,
  EMPTY_CHANNEL_REPORTS_FILTERS,
  useChannelReports,
} from "@posthog/ui/features/canvas/hooks/useChannelReports";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
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
  const { reports, isLoading, isError, markSeen } = useChannelReports(
    view,
    filters,
  );

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
      <div className="scroll-mask-4 min-h-0 flex-1 overflow-y-auto">{body}</div>
    </div>
  );
}
