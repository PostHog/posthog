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
  INBOX_RELEVANCE_SORT_KEY,
  INBOX_REPORT_STATE_OPTIONS,
  inboxPriorityFilterLabel,
  inboxReportStateFilterLabel,
  inboxSortMenuOptions,
  inboxSortOptionFromKey,
  inboxSortOptionKey,
} from "@posthog/ui/features/inbox/filterOptions";
import { useInboxRelevanceSort } from "@posthog/ui/features/inbox/hooks/useInboxRelevanceSort";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";

export function InboxReportFilters(): React.JSX.Element {
  const sortField = useInboxSignalsFilterStore((state) => state.sortField);
  const sortDirection = useInboxSignalsFilterStore(
    (state) => state.sortDirection,
  );
  const setSort = useInboxSignalsFilterStore((state) => state.setSort);
  const setRelevanceSort = useInboxSignalsFilterStore(
    (state) => state.setRelevanceSort,
  );
  const relevanceSort = useInboxRelevanceSort();
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

  const sortOptions = inboxSortMenuOptions(relevanceSort.available);
  const activeSortKey = relevanceSort.active
    ? INBOX_RELEVANCE_SORT_KEY
    : inboxSortOptionKey(sortField, sortDirection);

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
              {inboxReportStateFilterLabel(reportStateFilter)}
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
          {INBOX_REPORT_STATE_OPTIONS.map((option) => (
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
        items={sortOptions.map((option) => ({
          value: option.value,
          label: option.label,
        }))}
        onValueChange={(key) => {
          if (key === INBOX_RELEVANCE_SORT_KEY) {
            setRelevanceSort();
            return;
          }
          const option = inboxSortOptionFromKey(key ?? "");
          if (option) setSort(option.field, option.direction);
        }}
      >
        <SelectTrigger size="default" data-attr="inbox-sort">
          <span>Sort:</span>
          <SelectValue>
            {(selected: string) =>
              sortOptions.find((option) => option.value === selected)?.label ??
              selected
            }
          </SelectValue>
        </SelectTrigger>
        <SelectContent align="start" side="bottom" sideOffset={6}>
          {sortOptions.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
