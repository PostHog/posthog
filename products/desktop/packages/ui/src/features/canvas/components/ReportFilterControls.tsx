import { FunnelSimple as FunnelSimpleIcon } from "@phosphor-icons/react";
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

/**
 * The report filter row shared by the sidebar Reports tab and the space feed:
 * title search, a "Me" (suggested-reviewer) toggle, and a priority menu. State
 * is owned by the caller so each surface filters its own list.
 */
export function ReportFilterControls({
  filters,
  onChange,
}: {
  filters: ChannelReportsFilters;
  onChange: (filters: ChannelReportsFilters) => void;
}) {
  const filtersActive =
    filters.relevantToMeOnly || filters.priorities.length > 0;

  const togglePriority = (priority: SignalReportPriority) =>
    onChange({
      ...filters,
      priorities: filters.priorities.includes(priority)
        ? filters.priorities.filter((p) => p !== priority)
        : [...filters.priorities, priority],
    });

  return (
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
        aria-label="Show only reports relevant to me"
        aria-pressed={filters.relevantToMeOnly}
        onClick={() =>
          onChange({ ...filters, relevantToMeOnly: !filters.relevantToMeOnly })
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
                  onChange({
                    ...filters,
                    priorities: [],
                    relevantToMeOnly: false,
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
