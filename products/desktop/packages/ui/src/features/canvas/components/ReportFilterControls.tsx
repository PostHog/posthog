import { FunnelSimple as FunnelSimpleIcon } from "@phosphor-icons/react";
import type { ReportStatusFilter } from "@posthog/core/inbox/reportChannelScope";
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Input,
} from "@posthog/quill";
import type { SignalReportPriority } from "@posthog/shared/types";
import { cnHeaderButton } from "@posthog/ui/features/canvas/components/channelHeaderButton";
import type { ChannelReportsFilters } from "@posthog/ui/features/canvas/hooks/useChannelReports";

const PRIORITIES: SignalReportPriority[] = ["P0", "P1", "P2", "P3", "P4"];

// The old inbox tabs as filter choices — see matchesReportStatusFilter.
const STATUS_FILTERS: readonly {
  value: ReportStatusFilter;
  label: string;
}[] = [
  { value: "all", label: "All" },
  { value: "needs-review", label: "Needs review" },
  { value: "ready", label: "Ready" },
  { value: "running", label: "Running" },
  { value: "archived", label: "Archived" },
];

/**
 * The report filter row shared by the sidebar Reports tab and the space feed:
 * title search, a "Me" (suggested-reviewer) toggle, and a priority menu. State
 * is owned by the caller so each surface filters its own list.
 */
export function ReportFilterControls({
  filters,
  onChange,
  showStatusInMenu = true,
  showSearch = true,
}: {
  filters: ChannelReportsFilters;
  onChange: (filters: ChannelReportsFilters) => void;
  /** Off where visible status chips carry the choice instead (the feed). */
  showStatusInMenu?: boolean;
  /** Off where a shared search bar owns the query (the sidebar header). */
  showSearch?: boolean;
}) {
  const filtersActive =
    filters.relevantToMeOnly ||
    filters.priorities.length > 0 ||
    filters.status !== "all";

  const togglePriority = (priority: SignalReportPriority) =>
    onChange({
      ...filters,
      priorities: filters.priorities.includes(priority)
        ? filters.priorities.filter((p) => p !== priority)
        : [...filters.priorities, priority],
    });

  return (
    <>
      {showSearch && (
        <Input
          value={filters.search}
          onChange={(event) =>
            onChange({ ...filters, search: event.target.value })
          }
          placeholder="Search reports…"
          aria-label="Search reports"
          className="h-6 flex-1 text-[12px]"
        />
      )}
      <Button
        variant="default"
        size="icon-xs"
        aria-label="Show only reports suggested for me"
        aria-pressed={filters.relevantToMeOnly}
        onClick={() =>
          onChange({ ...filters, relevantToMeOnly: !filters.relevantToMeOnly })
        }
        className={`${cnHeaderButton(filters.relevantToMeOnly)} w-auto px-1.5`}
      >
        <span className="font-semibold text-[10px]">For you</span>
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="default"
              size="icon-xs"
              aria-label="Filter reports by status and priority"
              className={cnHeaderButton(
                filters.priorities.length > 0 || filters.status !== "all",
              )}
            >
              <FunnelSimpleIcon size={12} />
            </Button>
          }
        />
        <DropdownMenuContent align="end">
          {showStatusInMenu && (
            <>
              <DropdownMenuLabel>Status</DropdownMenuLabel>
              {STATUS_FILTERS.map(({ value, label }) => (
                <DropdownMenuCheckboxItem
                  key={value}
                  checked={filters.status === value}
                  closeOnClick={false}
                  onCheckedChange={() =>
                    onChange({ ...filters, status: value })
                  }
                >
                  {label}
                </DropdownMenuCheckboxItem>
              ))}
              <DropdownMenuSeparator />
            </>
          )}
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
                  onChange({
                    ...filters,
                    priorities: [],
                    relevantToMeOnly: false,
                    status: "all",
                  })
                }
              >
                Clear filters
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
}
