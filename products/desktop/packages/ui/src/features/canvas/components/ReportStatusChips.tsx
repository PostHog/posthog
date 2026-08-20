import type {
  ReportStatusCounts,
  ReportStatusFilter,
} from "@posthog/core/inbox/reportChannelScope";
import { Button } from "@posthog/quill";
import { cnHeaderButton } from "@posthog/ui/features/canvas/components/channelHeaderButton";
import type { ChannelReportsFilters } from "@posthog/ui/features/canvas/hooks/useChannelReports";

const CHIPS: readonly { value: ReportStatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "needs-review", label: "Needs review" },
  { value: "ready", label: "Ready" },
  { value: "running", label: "Running" },
  // Archived rows are a separate lazy fetch, so this chip's count only exists
  // while it is selected — it renders without a number otherwise.
  { value: "archived", label: "Archived" },
];

/**
 * The status buckets as visible chips with live counts — the old inbox tabs'
 * counts, worn by the filter that replaced them. Counts ignore the selected
 * status so a chip's number doesn't change when clicked.
 */
export function ReportStatusChips({
  filters,
  onChange,
  counts,
}: {
  filters: ChannelReportsFilters;
  onChange: (filters: ChannelReportsFilters) => void;
  counts: ReportStatusCounts;
}) {
  return (
    <div className="flex items-center gap-1">
      {CHIPS.map(({ value, label }) => (
        <Button
          key={value}
          variant="default"
          size="xs"
          aria-pressed={filters.status === value}
          onClick={() => onChange({ ...filters, status: value })}
          className={`${cnHeaderButton(filters.status === value)} gap-1 px-1.5 text-[11px]`}
        >
          {label}
          {(value !== "archived" || counts[value] > 0) && (
            <span className="text-(--gray-9) tabular-nums">
              {counts[value]}
            </span>
          )}
        </Button>
      ))}
    </div>
  );
}
