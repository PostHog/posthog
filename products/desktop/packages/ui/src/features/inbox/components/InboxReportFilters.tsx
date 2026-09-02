import { CaretDownIcon } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@posthog/quill";
import {
  INBOX_PRIORITY_OPTIONS,
  INBOX_SORT_OPTIONS,
  inboxPriorityFilterLabel,
  inboxSortOptionKey,
} from "@posthog/ui/features/inbox/filterOptions";
import {
  type InboxReportStateFilter,
  useInboxSignalsFilterStore,
} from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";

const REPORT_STATE_OPTIONS: {
  value: InboxReportStateFilter;
  label: string;
}[] = [
  { value: "review_and_merge", label: "Review and merge" },
  { value: "needs_decision", label: "Needs decision" },
  { value: "resolved", label: "Resolved" },
  { value: "dismissed", label: "Dismissed" },
];

function reportStateFilterLabel(selected: InboxReportStateFilter[]): string {
  if (selected.length === 0) return "All statuses";
  if (selected.length === 1) {
    return (
      REPORT_STATE_OPTIONS.find((option) => option.value === selected[0])
        ?.label ?? "1 status"
    );
  }
  return `${selected.length} statuses`;
}

export function InboxReportFilters(): React.JSX.Element {
  const sortField = useInboxSignalsFilterStore((state) => state.sortField);
  const sortDirection = useInboxSignalsFilterStore(
    (state) => state.sortDirection,
  );
  const setSort = useInboxSignalsFilterStore((state) => state.setSort);
  const priorityFilter = useInboxSignalsFilterStore(
    (state) => state.priorityFilter,
  );
  const togglePriority = useInboxSignalsFilterStore(
    (state) => state.togglePriority,
  );
  const reportStateFilter = useInboxSignalsFilterStore(
    (state) => state.reportStateFilter,
  );
  const toggleReportState = useInboxSignalsFilterStore(
    (state) => state.toggleReportState,
  );

  const activeSortKey = inboxSortOptionKey(sortField, sortDirection);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              type="button"
              variant="outline"
              size="default"
              data-attr="inbox-filter-priority"
            >
              {inboxPriorityFilterLabel(priorityFilter)}
              <CaretDownIcon size={12} />
            </Button>
          }
        />
        <DropdownMenuContent align="start" side="bottom" sideOffset={6}>
          {INBOX_PRIORITY_OPTIONS.map((option) => (
            <DropdownMenuCheckboxItem
              key={option.value}
              checked={priorityFilter.includes(option.value)}
              closeOnClick={false}
              onCheckedChange={() => togglePriority(option.value)}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: option.accent }}
              />
              {option.value}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              type="button"
              variant="outline"
              size="default"
              data-attr="inbox-filter-state"
            >
              {reportStateFilterLabel(reportStateFilter)}
              <CaretDownIcon size={12} />
            </Button>
          }
        />
        <DropdownMenuContent
          align="start"
          side="bottom"
          sideOffset={6}
          className="min-w-48"
        >
          {REPORT_STATE_OPTIONS.map((option) => (
            <DropdownMenuCheckboxItem
              key={option.value}
              checked={reportStateFilter.includes(option.value)}
              closeOnClick={false}
              onCheckedChange={() => toggleReportState(option.value)}
            >
              {option.label}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <Select
        value={activeSortKey}
        items={INBOX_SORT_OPTIONS.map((option) => ({
          value: inboxSortOptionKey(option.field, option.direction),
          label: option.label,
        }))}
        onValueChange={(key) => {
          const option = INBOX_SORT_OPTIONS.find(
            (candidate) =>
              inboxSortOptionKey(candidate.field, candidate.direction) === key,
          );
          if (option) setSort(option.field, option.direction);
        }}
      >
        <SelectTrigger size="default" data-attr="inbox-sort">
          <span>Sort:</span>
          <SelectValue>
            {(selected: string) =>
              INBOX_SORT_OPTIONS.find(
                (option) =>
                  inboxSortOptionKey(option.field, option.direction) ===
                  selected,
              )?.label ?? selected
            }
          </SelectValue>
        </SelectTrigger>
        <SelectContent align="start" side="bottom" sideOffset={6}>
          {INBOX_SORT_OPTIONS.map((option) => (
            <SelectItem
              key={inboxSortOptionKey(option.field, option.direction)}
              value={inboxSortOptionKey(option.field, option.direction)}
            >
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
