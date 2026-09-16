import { getAuthIdentity } from "@posthog/core/auth/authIdentity";
import {
  DropdownMenuCheckboxItem,
  DropdownMenuSeparator,
  MenuLabel,
} from "@posthog/quill";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  type ActivityInboxScope,
  hasActiveActivityMenuFilters,
  useActivityFilterStore,
} from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useReportsInboxEnabled } from "@posthog/ui/features/feature-flags/useReportsInboxEnabled";
import {
  INBOX_PRIORITY_MENU_OPTIONS,
  INBOX_SORT_MENU_OPTIONS,
  inboxPriorityFilterLabel,
  inboxSortOptionFromKey,
  inboxSortOptionKey,
  inboxSourceFilterLabel,
} from "@posthog/ui/features/inbox/filterOptions";
import { useInboxSourceFilterOptions } from "@posthog/ui/features/inbox/hooks/useInboxSourceFilterOptions";
import type { InboxPrFilter } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import {
  FilterCheckboxSubMenu,
  FilterClearItem,
  type FilterOption,
  FilterRadioSubMenu,
} from "@posthog/ui/primitives/FilterMenu";
import type { ReactElement } from "react";

const SCOPE_OPTIONS: readonly FilterOption<ActivityInboxScope>[] = [
  { value: "for-you", label: "For you" },
  { value: "entire-project", label: "Entire project" },
];

const REPORT_OPTIONS: readonly FilterOption<InboxPrFilter>[] = [
  { value: "all", label: "All reports" },
  { value: "with_pr", label: "Has a PR" },
  { value: "without_pr", label: "No PR yet" },
];

export function ActivityIncludeMenuSection(): ReactElement {
  const reportsInboxEnabled = useReportsInboxEnabled();
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const mentionsEnabled = useActivityFilterStore(
    (state) => state.mentionsEnabled,
  );
  const setMentionsEnabled = useActivityFilterStore(
    (state) => state.setMentionsEnabled,
  );
  const inboxEnabled = useActivityFilterStore((state) =>
    authIdentity
      ? (state.inboxEnabledByAuthIdentity[authIdentity] ?? false)
      : false,
  );
  const setInboxEnabled = useActivityFilterStore(
    (state) => state.setInboxEnabled,
  );
  const inboxScope = useActivityFilterStore((state) => state.inboxScope);
  const setInboxScope = useActivityFilterStore((state) => state.setInboxScope);
  const sourceProductFilter = useActivityFilterStore(
    (state) => state.inboxSourceProductFilter,
  );
  const toggleSourceProduct = useActivityFilterStore(
    (state) => state.toggleInboxSourceProduct,
  );
  const clearSourceProductFilter = useActivityFilterStore(
    (state) => state.clearInboxSourceProductFilter,
  );
  const prFilter = useActivityFilterStore((state) => state.inboxPrFilter);
  const setPrFilter = useActivityFilterStore((state) => state.setInboxPrFilter);
  const sortField = useActivityFilterStore((state) => state.inboxSortField);
  const sortDirection = useActivityFilterStore(
    (state) => state.inboxSortDirection,
  );
  const setSort = useActivityFilterStore((state) => state.setInboxSort);
  const priorityFilter = useActivityFilterStore(
    (state) => state.inboxPriorityFilter,
  );
  const togglePriority = useActivityFilterStore(
    (state) => state.toggleInboxPriority,
  );
  const clearPriorityFilter = useActivityFilterStore(
    (state) => state.clearInboxPriorityFilter,
  );
  const resetMenuFilters = useActivityFilterStore(
    (state) => state.resetMenuFilters,
  );
  const filtersActive = useActivityFilterStore((state) =>
    hasActiveActivityMenuFilters(state, authIdentity),
  );
  const inboxAvailable = reportsInboxEnabled && authIdentity !== null;
  const sourceOptions = useInboxSourceFilterOptions(sourceProductFilter, {
    enabled: inboxAvailable && inboxEnabled,
  });
  return (
    <>
      <MenuLabel>Include</MenuLabel>
      <DropdownMenuCheckboxItem
        checked={mentionsEnabled}
        closeOnClick={false}
        onCheckedChange={setMentionsEnabled}
      >
        Mentions
      </DropdownMenuCheckboxItem>
      {inboxAvailable && (
        <DropdownMenuCheckboxItem
          checked={inboxEnabled}
          closeOnClick={false}
          onCheckedChange={(enabled) => setInboxEnabled(authIdentity, enabled)}
        >
          Self-driving
        </DropdownMenuCheckboxItem>
      )}

      {inboxAvailable && inboxEnabled && (
        <>
          <DropdownMenuSeparator />
          <MenuLabel>Self-driving</MenuLabel>
          <FilterRadioSubMenu
            label="Scope"
            options={SCOPE_OPTIONS}
            value={inboxScope}
            defaultValue="for-you"
            onChange={setInboxScope}
          />
          <FilterCheckboxSubMenu
            label="Source"
            summary={inboxSourceFilterLabel(sourceProductFilter)}
            allLabel="All sources"
            options={sourceOptions}
            selected={sourceProductFilter}
            onToggle={toggleSourceProduct}
            onClear={clearSourceProductFilter}
          />
          <FilterRadioSubMenu
            label="Reports"
            options={REPORT_OPTIONS}
            value={prFilter}
            defaultValue="all"
            onChange={setPrFilter}
          />
          <FilterRadioSubMenu
            label="Sort by"
            options={INBOX_SORT_MENU_OPTIONS}
            value={inboxSortOptionKey(sortField, sortDirection)}
            defaultValue={inboxSortOptionKey("priority", "asc")}
            onChange={(key) => {
              const option = inboxSortOptionFromKey(key);
              if (option) setSort(option.field, option.direction);
            }}
          />
          <FilterCheckboxSubMenu
            label="Priority"
            summary={inboxPriorityFilterLabel(priorityFilter)}
            allLabel="All priorities"
            options={INBOX_PRIORITY_MENU_OPTIONS}
            selected={priorityFilter}
            onToggle={togglePriority}
            onClear={clearPriorityFilter}
          />
        </>
      )}
      <FilterClearItem
        active={filtersActive}
        dataAttr="clear-activity-filters"
        onClear={() => resetMenuFilters(authIdentity)}
      />
    </>
  );
}
