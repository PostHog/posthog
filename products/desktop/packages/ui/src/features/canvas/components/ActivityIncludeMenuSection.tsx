import { getAuthIdentity } from "@posthog/core/auth/authIdentity";
import {
  cn,
  DropdownMenuCheckboxItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  MenuLabel,
} from "@posthog/quill";
import type { SourceProduct } from "@posthog/shared/types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  type ActivityInboxScope,
  useActivityFilterStore,
} from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useReportsInboxEnabled } from "@posthog/ui/features/feature-flags/useReportsInboxEnabled";
import {
  INBOX_PRIORITY_OPTIONS,
  INBOX_SORT_OPTIONS,
  inboxPriorityFilterLabel,
  inboxSourceFilterLabel,
} from "@posthog/ui/features/inbox/filterOptions";
import { useInboxSourceFilterOptions } from "@posthog/ui/features/inbox/hooks/useInboxSourceFilterOptions";
import type { InboxPrFilter } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { type ReactElement, useMemo } from "react";

const SCOPE_OPTIONS: readonly {
  value: ActivityInboxScope;
  label: string;
}[] = [
  { value: "for-you", label: "For you" },
  { value: "entire-project", label: "Entire project" },
];

const REPORT_OPTIONS: readonly { value: InboxPrFilter; label: string }[] = [
  { value: "all", label: "All reports" },
  { value: "with_pr", label: "Has a PR" },
  { value: "without_pr", label: "No PR yet" },
];

function selectedLabel<T extends string>(
  options: readonly { value: T; label: string }[],
  value: T,
): string {
  return options.find((option) => option.value === value)?.label ?? "";
}

function ActivityFilterValue({
  label,
  value,
  active,
}: {
  label: string;
  value: string;
  active: boolean;
}): ReactElement {
  return (
    <>
      <span>{label}</span>
      <span
        className={cn(
          "flex-1 pl-4 text-right",
          active ? "text-primary" : "text-muted-foreground/80",
        )}
      >
        {value}
      </span>
    </>
  );
}

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
  const inboxAvailable = reportsInboxEnabled && authIdentity !== null;
  const sourceOptions = useInboxSourceFilterOptions(sourceProductFilter, {
    enabled: inboxAvailable && inboxEnabled,
  });
  const selectedSources = useMemo(
    () => new Set(sourceProductFilter),
    [sourceProductFilter],
  );
  const activeSort = INBOX_SORT_OPTIONS.find(
    (option) =>
      option.field === sortField && option.direction === sortDirection,
  );

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
          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="pr-1">
              <ActivityFilterValue
                label="Scope"
                value={selectedLabel(SCOPE_OPTIONS, inboxScope)}
                active={inboxScope !== "for-you"}
              />
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent side="right" sideOffset={4}>
              <DropdownMenuRadioGroup
                value={inboxScope}
                onValueChange={(value) =>
                  setInboxScope(value as ActivityInboxScope)
                }
              >
                {SCOPE_OPTIONS.map((option) => (
                  <DropdownMenuRadioItem
                    key={option.value}
                    value={option.value}
                  >
                    {option.label}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="pr-1">
              <ActivityFilterValue
                label="Source"
                value={inboxSourceFilterLabel(sourceProductFilter)}
                active={sourceProductFilter.length > 0}
              />
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent side="right" sideOffset={4}>
              <DropdownMenuCheckboxItem
                checked={sourceProductFilter.length === 0}
                closeOnClick={false}
                onCheckedChange={clearSourceProductFilter}
              >
                All sources
              </DropdownMenuCheckboxItem>
              {sourceOptions.map((option) => (
                <DropdownMenuCheckboxItem
                  key={option.value}
                  checked={selectedSources.has(option.value)}
                  closeOnClick={false}
                  onCheckedChange={() =>
                    toggleSourceProduct(option.value as SourceProduct)
                  }
                >
                  {option.icon}
                  {option.label}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="pr-1">
              <ActivityFilterValue
                label="Reports"
                value={selectedLabel(REPORT_OPTIONS, prFilter)}
                active={prFilter !== "all"}
              />
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent side="right" sideOffset={4}>
              <DropdownMenuRadioGroup
                value={prFilter}
                onValueChange={(value) => setPrFilter(value as InboxPrFilter)}
              >
                {REPORT_OPTIONS.map((option) => (
                  <DropdownMenuRadioItem
                    key={option.value}
                    value={option.value}
                  >
                    {option.label}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="pr-1">
              <ActivityFilterValue
                label="Sort by"
                value={activeSort?.label ?? "Priority first"}
                active={sortField !== "priority" || sortDirection !== "asc"}
              />
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent side="right" sideOffset={4}>
              <DropdownMenuRadioGroup
                value={`${sortField}:${sortDirection}`}
                onValueChange={(value) => {
                  const option = INBOX_SORT_OPTIONS.find(
                    (candidate) =>
                      `${candidate.field}:${candidate.direction}` === value,
                  );
                  if (option) setSort(option.field, option.direction);
                }}
              >
                {INBOX_SORT_OPTIONS.map((option) => (
                  <DropdownMenuRadioItem
                    key={`${option.field}:${option.direction}`}
                    value={`${option.field}:${option.direction}`}
                  >
                    {option.icon}
                    {option.label}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="pr-1">
              <ActivityFilterValue
                label="Priority"
                value={inboxPriorityFilterLabel(priorityFilter)}
                active={priorityFilter.length > 0}
              />
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent side="right" sideOffset={4}>
              <DropdownMenuCheckboxItem
                checked={priorityFilter.length === 0}
                closeOnClick={false}
                onCheckedChange={clearPriorityFilter}
              >
                All priorities
              </DropdownMenuCheckboxItem>
              {INBOX_PRIORITY_OPTIONS.map((option) => (
                <DropdownMenuCheckboxItem
                  key={option.value}
                  checked={priorityFilter.includes(option.value)}
                  closeOnClick={false}
                  onCheckedChange={() => togglePriority(option.value)}
                >
                  <span
                    aria-hidden
                    className="size-2 shrink-0 rounded-full"
                    style={{ backgroundColor: option.accent }}
                  />
                  {option.value}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        </>
      )}
    </>
  );
}
