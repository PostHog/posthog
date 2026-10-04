import {
  INBOX_SCOPE_ENTIRE_PROJECT,
  INBOX_SCOPE_FOR_YOU,
  type InboxScope,
  parseTeammateInboxScope,
  teammateInboxScope,
} from "@posthog/core/inbox/reportMembership";
import { DropdownMenu, DropdownMenuContent } from "@posthog/quill";
import {
  getSuggestedReviewerDisplayName,
  INBOX_ANY_CREATED_WINDOW,
  INBOX_CREATED_WINDOW_MENU_OPTIONS,
  INBOX_PRIORITY_MENU_OPTIONS,
  INBOX_REPORT_STATE_OPTIONS,
  inboxCreatedWindowFromMenuValue,
  inboxPriorityFilterLabel,
  inboxReportStateFilterLabel,
  inboxSortMenuOptions,
  inboxSortOptionFromKey,
  inboxSortOptionKey,
  isDefaultInboxReportStateFilter,
} from "@posthog/ui/features/inbox/filterOptions";
import { useInboxActiveSort } from "@posthog/ui/features/inbox/hooks/useInboxActiveSort";
import { useInboxScopeOptions } from "@posthog/ui/features/inbox/hooks/useInboxScopeOptions";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import {
  FilterCheckboxSubMenu,
  FilterClearItem,
  FilterMenuTrigger,
  type FilterOption,
  FilterRadioSubMenu,
} from "@posthog/ui/primitives/FilterMenu";
import { type ReactElement, useState } from "react";

const DEFAULT_SORT_KEY = inboxSortOptionKey("created_at", "desc");

export function InboxFilterMenu({
  active,
  onClearFilters,
}: {
  active: boolean;
  onClearFilters: () => void;
}): ReactElement {
  const [activated, setActivated] = useState(false);

  return (
    <DropdownMenu
      onOpenChange={(open) => {
        if (open) setActivated(true);
      }}
    >
      <FilterMenuTrigger
        active={active}
        label="Filter reports"
        dataAttr="inbox-pane-filter"
      />
      {/* The reviewer list is a request of its own, so it waits for a first
          open rather than firing on every visit to the pane. */}
      {activated && (
        <InboxFilterMenuContent
          active={active}
          onClearFilters={onClearFilters}
        />
      )}
    </DropdownMenu>
  );
}

function InboxFilterMenuContent({
  active,
  onClearFilters,
}: {
  active: boolean;
  onClearFilters: () => void;
}): ReactElement {
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
  const setPriorityFilter = useInboxSignalsFilterStore(
    (state) => state.setPriorityFilter,
  );
  const reportStateFilter = useInboxSignalsFilterStore(
    (state) => state.reportStateFilter,
  );
  const toggleReportState = useInboxSignalsFilterStore(
    (state) => state.toggleReportState,
  );
  const setReportStateFilter = useInboxSignalsFilterStore(
    (state) => state.setReportStateFilter,
  );
  const scope = useInboxReviewerScopeStore((state) => state.scope);
  const setScope = useInboxReviewerScopeStore((state) => state.setScope);
  const { teammateOptions } = useInboxScopeOptions();

  const activeSortKey = inboxSortOptionKey(sortField, sortDirection);
  const teammateUuid = parseTeammateInboxScope(scope);
  const selectedTeammate = teammateUuid
    ? teammateOptions.find((option) => option.uuid === teammateUuid)
    : undefined;
  const scopeOptions: FilterOption<InboxScope>[] = [
    { value: INBOX_SCOPE_FOR_YOU, label: "For you" },
    { value: INBOX_SCOPE_ENTIRE_PROJECT, label: "Entire project" },
    ...teammateOptions.map((teammate) => ({
      value: teammateInboxScope(teammate.uuid),
      label: getSuggestedReviewerDisplayName(teammate),
      searchLabel: teammate.email,
    })),
  ];

  return (
    <DropdownMenuContent
      align="end"
      side="bottom"
      sideOffset={6}
      className="min-w-64"
      aria-label="Filter reports"
    >
      <FilterCheckboxSubMenu
        label="Status"
        summary={inboxReportStateFilterLabel(reportStateFilter)}
        allLabel="All statuses"
        options={INBOX_REPORT_STATE_OPTIONS}
        selected={reportStateFilter}
        active={!isDefaultInboxReportStateFilter(reportStateFilter)}
        onToggle={toggleReportState}
        onClear={() => setReportStateFilter([])}
      />
      <FilterCheckboxSubMenu
        label="Priority"
        summary={inboxPriorityFilterLabel(priorityFilter)}
        allLabel="All priorities"
        options={INBOX_PRIORITY_MENU_OPTIONS}
        selected={priorityFilter}
        onToggle={togglePriority}
        onClear={() => setPriorityFilter([])}
      />
      {timeWindowAvailable && (
        <FilterRadioSubMenu
          label="Created"
          options={INBOX_CREATED_WINDOW_MENU_OPTIONS}
          value={createdWindow ?? INBOX_ANY_CREATED_WINDOW}
          defaultValue={INBOX_ANY_CREATED_WINDOW}
          onChange={(value) =>
            setCreatedWindow(inboxCreatedWindowFromMenuValue(value))
          }
        />
      )}
      <FilterRadioSubMenu
        label="Sort by"
        options={inboxSortMenuOptions(modelSortAvailable)}
        value={activeSortKey}
        defaultValue={DEFAULT_SORT_KEY}
        onChange={(key) => {
          const option = inboxSortOptionFromKey(key);
          if (option) selectSort(option.field, option.direction);
        }}
      />
      <FilterRadioSubMenu
        label="Scope"
        searchPlaceholder="Search users…"
        options={scopeOptions}
        value={scope}
        defaultValue={INBOX_SCOPE_FOR_YOU}
        // A teammate scope outlives the list that names them, so the row falls
        // back to the id's own label rather than going blank.
        valueLabel={
          selectedTeammate
            ? getSuggestedReviewerDisplayName(selectedTeammate)
            : undefined
        }
        onChange={setScope}
      />
      <FilterClearItem
        active={active}
        dataAttr="clear-inbox-pane-filters"
        onClear={onClearFilters}
      />
    </DropdownMenuContent>
  );
}
