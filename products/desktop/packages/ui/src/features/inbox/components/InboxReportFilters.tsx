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
  INBOX_ANY_CREATED_WINDOW,
  INBOX_CREATED_WINDOW_MENU_OPTIONS,
  INBOX_PRIORITY_OPTIONS,
  INBOX_REPORT_STATE_OPTIONS,
  inboxCreatedWindowFromMenuValue,
  inboxPriorityFilterLabel,
  inboxReportStateFilterLabel,
  inboxSortOptionFromKey,
  inboxSortOptionKey,
  inboxSortOptions,
} from "@posthog/ui/features/inbox/filterOptions";
import { useInboxActiveSort } from "@posthog/ui/features/inbox/hooks/useInboxActiveSort";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";

export function InboxReportFilters(): React.JSX.Element {
  const {
    sortField,
    sortDirection,
    createdWindow,
    modelSortAvailable,
    timeWindowAvailable,
    selectSort,
  } = useInboxActiveSort();
  const setCreatedWindow = useInboxSignalsFilterStore(
    (state) => state.setCreatedWindow,
  );
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
  const sortOptions = inboxSortOptions(modelSortAvailable);

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

      {timeWindowAvailable && (
        <Select
          value={createdWindow ?? INBOX_ANY_CREATED_WINDOW}
          items={INBOX_CREATED_WINDOW_MENU_OPTIONS}
          onValueChange={(value) =>
            setCreatedWindow(inboxCreatedWindowFromMenuValue(value ?? ""))
          }
        >
          <SelectTrigger size="default" data-attr="inbox-created-window">
            <span>Created:</span>
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="start" side="bottom" sideOffset={6}>
            {INBOX_CREATED_WINDOW_MENU_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      <Select
        value={activeSortKey}
        items={sortOptions.map((option) => ({
          value: inboxSortOptionKey(option.field, option.direction),
          label: option.label,
        }))}
        onValueChange={(key) => {
          const option = inboxSortOptionFromKey(key ?? "");
          if (option) selectSort(option.field, option.direction);
        }}
      >
        <SelectTrigger size="default" data-attr="inbox-sort">
          <span>Sort:</span>
          <SelectValue>
            {(selected: string) =>
              inboxSortOptionFromKey(selected)?.label ?? selected
            }
          </SelectValue>
        </SelectTrigger>
        <SelectContent align="start" side="bottom" sideOffset={6}>
          {sortOptions.map((option) => (
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
