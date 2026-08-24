import { FunnelSimple as FunnelSimpleIcon } from "@phosphor-icons/react";
import type { ReportStatusFilter } from "@posthog/core/inbox/reportChannelScope";
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
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
 * The report filters shared by the sidebar Reports tab and the space feed.
 * State is owned by the caller so each surface filters its own list. In
 * `compact` mode (the sidebar header, where the tabs already fill the row)
 * everything folds into the one funnel menu; the feed keeps the labeled
 * search / "For you" controls beside it.
 */
export function ReportFilterControls({
  filters,
  onChange,
  showStatusInMenu = true,
  compact = false,
}: {
  filters: ChannelReportsFilters;
  onChange: (filters: ChannelReportsFilters) => void;
  /** Off where visible status chips carry the choice instead (the feed). */
  showStatusInMenu?: boolean;
  /**
   * The funnel menu only: no search input (a shared bar owns the query) and
   * "For you" as a menu checkbox instead of a labeled button. For the narrow
   * sidebar header, which has no room beside the tabs.
   */
  compact?: boolean;
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
      {!compact && (
        <>
          <Input
            value={filters.search}
            onChange={(event) =>
              onChange({ ...filters, search: event.target.value })
            }
            placeholder="Search reports…"
            aria-label="Search reports"
            className="h-6 flex-1 text-[12px]"
          />
          <Button
            variant="default"
            size="icon-xs"
            aria-label="Show only reports suggested for me"
            aria-pressed={filters.relevantToMeOnly}
            onClick={() =>
              onChange({
                ...filters,
                relevantToMeOnly: !filters.relevantToMeOnly,
              })
            }
            className={`${cnHeaderButton(filters.relevantToMeOnly)} w-auto px-1.5`}
          >
            <span className="font-semibold text-[10px]">For you</span>
          </Button>
        </>
      )}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="default"
              size="icon-xs"
              aria-label="Filter reports"
              className={cnHeaderButton(
                compact
                  ? filtersActive
                  : filters.priorities.length > 0 || filters.status !== "all",
              )}
            >
              <FunnelSimpleIcon size={12} />
            </Button>
          }
        />
        <DropdownMenuContent align="end">
          {compact && (
            <>
              <DropdownMenuCheckboxItem
                checked={filters.relevantToMeOnly}
                closeOnClick={false}
                onCheckedChange={() =>
                  onChange({
                    ...filters,
                    relevantToMeOnly: !filters.relevantToMeOnly,
                  })
                }
              >
                For you
              </DropdownMenuCheckboxItem>
              <DropdownMenuSeparator />
            </>
          )}
          {showStatusInMenu && (
            <>
              {/* Labels crash outside a group (Base UI MenuGroupLabel). */}
              <DropdownMenuGroup>
                <DropdownMenuLabel>Status</DropdownMenuLabel>
                {/* Status is one choice, so it reads as radios; priority below
                    stacks, so it keeps checkboxes. */}
                <DropdownMenuRadioGroup
                  value={filters.status}
                  onValueChange={(value) =>
                    onChange({
                      ...filters,
                      status: value as ReportStatusFilter,
                    })
                  }
                >
                  {STATUS_FILTERS.map(({ value, label }) => (
                    <DropdownMenuRadioItem
                      key={value}
                      value={value}
                      closeOnClick={false}
                    >
                      {label}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
            </>
          )}
          <DropdownMenuGroup>
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
          </DropdownMenuGroup>
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
