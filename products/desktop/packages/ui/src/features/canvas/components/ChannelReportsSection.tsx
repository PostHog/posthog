import {
  FileMagnifyingGlassIcon,
  FunnelSimple as FunnelSimpleIcon,
} from "@phosphor-icons/react";
import type { ReportChannelView } from "@posthog/core/inbox/reportChannelScope";
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Input,
  Skeleton,
} from "@posthog/quill";
import type { SignalReportPriority } from "@posthog/shared/types";
import { cnHeaderButton } from "@posthog/ui/features/canvas/components/channelHeaderButton";
import { ReportRow } from "@posthog/ui/features/canvas/components/ReportRow";
import {
  type ChannelReportsFilters,
  EMPTY_CHANNEL_REPORTS_FILTERS,
  useChannelReports,
} from "@posthog/ui/features/canvas/hooks/useChannelReports";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
import { useMemo, useState } from "react";

const PRIORITIES: SignalReportPriority[] = ["P0", "P1", "P2", "P3", "P4"];

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
  const { reports, isLoading, isError } = useChannelReports(view, filters);

  const filtersActive =
    filters.relevantToMeOnly || filters.priorities.length > 0;

  const togglePriority = (priority: SignalReportPriority) =>
    setFilters((prev) => ({
      ...prev,
      priorities: prev.priorities.includes(priority)
        ? prev.priorities.filter((p) => p !== priority)
        : [...prev.priorities, priority],
    }));

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
        <Input
          value={filters.search}
          onChange={(event) =>
            setFilters((prev) => ({ ...prev, search: event.target.value }))
          }
          placeholder="Search reports…"
          aria-label="Search reports"
          className="h-6 flex-1 text-[12px]"
        />
        <Button
          variant="default"
          size="icon-xs"
          aria-label="Show only reports relevant to me"
          aria-pressed={filters.relevantToMeOnly}
          onClick={() =>
            setFilters((prev) => ({
              ...prev,
              relevantToMeOnly: !prev.relevantToMeOnly,
            }))
          }
          className={cnHeaderButton(filters.relevantToMeOnly)}
        >
          <span className="font-semibold text-[10px]">Me</span>
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant="default"
                size="icon-xs"
                aria-label="Filter reports by priority"
                className={cnHeaderButton(filters.priorities.length > 0)}
              >
                <FunnelSimpleIcon size={12} />
              </Button>
            }
          />
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Priority</DropdownMenuLabel>
            {PRIORITIES.map((priority) => (
              <DropdownMenuCheckboxItem
                key={priority}
                checked={filters.priorities.includes(priority)}
                closeOnClick={false}
                onCheckedChange={() => togglePriority(priority)}
              >
                {priority}
              </DropdownMenuCheckboxItem>
            ))}
            {filtersActive && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() =>
                    setFilters((prev) => ({
                      ...prev,
                      priorities: [],
                      relevantToMeOnly: false,
                    }))
                  }
                >
                  Clear filters
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="scroll-mask-4 min-h-0 flex-1 overflow-y-auto">{body}</div>
    </div>
  );
}
