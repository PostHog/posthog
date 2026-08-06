import {
  ArrowsClockwiseIcon,
  ArrowsDownUpIcon,
  CaretDownIcon,
  CheckIcon,
  CrosshairSimpleIcon,
  FlagIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react";
import { Popover, PopoverContent, PopoverTrigger } from "@posthog/quill";
import {
  INBOX_PRIORITY_OPTIONS,
  INBOX_SORT_OPTIONS,
  INBOX_SOURCE_OPTIONS,
  inboxPriorityFilterLabel,
  inboxSortOptionKey,
  inboxSourceFilterLabel,
} from "@posthog/ui/features/inbox/filterOptions";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { type ReactNode, useId } from "react";

interface InboxSearchFilterBarProps {
  searchPlaceholder?: string;
  onRefresh?: () => void;
  refreshing?: boolean;
}

const FILTER_ITEM_CLASS =
  "flex w-full items-center justify-between rounded-sm px-1.5 py-1 text-left text-[13px] text-gray-12 transition-colors hover:bg-(--gray-3) focus-visible:bg-(--gray-3) focus-visible:outline-none";

export function InboxSearchFilterBar({
  searchPlaceholder = "Search by title or description…",
  onRefresh,
  refreshing = false,
}: InboxSearchFilterBarProps) {
  const inputId = useId();
  const searchQuery = useInboxSignalsFilterStore((s) => s.searchQuery);
  const setSearchQuery = useInboxSignalsFilterStore((s) => s.setSearchQuery);
  const sortField = useInboxSignalsFilterStore((s) => s.sortField);
  const sortDirection = useInboxSignalsFilterStore((s) => s.sortDirection);
  const setSort = useInboxSignalsFilterStore((s) => s.setSort);
  const sourceProductFilter = useInboxSignalsFilterStore(
    (s) => s.sourceProductFilter,
  );
  const toggleSourceProduct = useInboxSignalsFilterStore(
    (s) => s.toggleSourceProduct,
  );
  const clearSourceProductFilter = useInboxSignalsFilterStore(
    (s) => s.clearSourceProductFilter,
  );
  const priorityFilter = useInboxSignalsFilterStore((s) => s.priorityFilter);
  const togglePriority = useInboxSignalsFilterStore((s) => s.togglePriority);
  const setPriorityFilter = useInboxSignalsFilterStore(
    (s) => s.setPriorityFilter,
  );

  const activeSort = INBOX_SORT_OPTIONS.find(
    (option) =>
      option.field === sortField && option.direction === sortDirection,
  );
  const activeSortKey = inboxSortOptionKey(sortField, sortDirection);
  const sortActive = activeSortKey !== "priority:asc";

  return (
    <div className="flex w-full flex-wrap items-center gap-2">
      <label
        htmlFor={inputId}
        className="flex h-8 min-w-[220px] flex-1 items-center gap-2 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-2.5 transition-colors focus-within:border-(--gray-8) hover:border-(--gray-6)"
      >
        <MagnifyingGlassIcon size={13} className="shrink-0 text-gray-10" />
        <input
          id={inputId}
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={searchPlaceholder}
          className="min-w-0 flex-1 bg-transparent text-[12.5px] text-gray-12 outline-none placeholder:text-(--gray-9)"
        />
      </label>

      <InboxFilterPopover
        label="Source"
        value={inboxSourceFilterLabel(sourceProductFilter)}
        icon={<CrosshairSimpleIcon size={13} />}
        active={sourceProductFilter.length > 0}
      >
        <div className="flex flex-col">
          <InboxFilterAnyItem
            active={sourceProductFilter.length === 0}
            onClick={clearSourceProductFilter}
          />
          {INBOX_SOURCE_OPTIONS.map((option) => {
            const isActive = sourceProductFilter.includes(option.value);
            return (
              <button
                key={option.value}
                type="button"
                className={FILTER_ITEM_CLASS}
                onClick={() => toggleSourceProduct(option.value)}
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  {option.icon}
                  <span className="truncate">{option.label}</span>
                </span>
                {isActive ? (
                  <CheckIcon size={12} className="shrink-0 text-gray-12" />
                ) : null}
              </button>
            );
          })}
        </div>
      </InboxFilterPopover>

      <InboxFilterPopover
        label="Sort"
        value={activeSort?.label ?? "Priority"}
        icon={<ArrowsDownUpIcon size={13} />}
        active={sortActive}
      >
        <div className="flex flex-col">
          {INBOX_SORT_OPTIONS.map((option) => {
            const isActive =
              sortField === option.field && sortDirection === option.direction;
            return (
              <button
                key={inboxSortOptionKey(option.field, option.direction)}
                type="button"
                className={FILTER_ITEM_CLASS}
                onClick={() => setSort(option.field, option.direction)}
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  {option.icon}
                  <span>{option.label}</span>
                </span>
                {isActive ? (
                  <CheckIcon size={12} className="shrink-0 text-gray-12" />
                ) : null}
              </button>
            );
          })}
        </div>
      </InboxFilterPopover>

      <InboxFilterPopover
        label="Priority"
        value={inboxPriorityFilterLabel(priorityFilter)}
        icon={<FlagIcon size={13} />}
        active={priorityFilter.length > 0}
      >
        <div className="flex flex-col">
          <InboxFilterAnyItem
            active={priorityFilter.length === 0}
            onClick={() => setPriorityFilter([])}
          />
          {INBOX_PRIORITY_OPTIONS.map((option) => {
            const isActive = priorityFilter.includes(option.value);
            return (
              <button
                key={option.value}
                type="button"
                className={FILTER_ITEM_CLASS}
                onClick={() => togglePriority(option.value)}
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  <span
                    className="inline-block h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: option.accent }}
                  />
                  <span>{option.value}</span>
                </span>
                {isActive ? (
                  <CheckIcon size={12} className="shrink-0 text-gray-12" />
                ) : null}
              </button>
            );
          })}
        </div>
      </InboxFilterPopover>

      {onRefresh ? (
        <Tooltip content="Refresh reports">
          <button
            type="button"
            aria-label="Refresh reports"
            disabled={refreshing}
            onClick={onRefresh}
            className="flex h-8 shrink-0 items-center rounded-(--radius-2) border border-transparent px-2 text-gray-10 transition-colors hover:border-(--gray-6) hover:bg-(--gray-2) hover:text-gray-12 focus-visible:outline-none disabled:pointer-events-none"
          >
            <ArrowsClockwiseIcon
              size={13}
              className={refreshing ? "animate-spin" : undefined}
            />
          </button>
        </Tooltip>
      ) : null}
    </div>
  );
}

function InboxFilterAnyItem({
  active,
  onClick,
}: {
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" className={FILTER_ITEM_CLASS} onClick={onClick}>
      <span className="truncate">Any</span>
      {active ? (
        <CheckIcon size={12} className="shrink-0 text-gray-12" />
      ) : null}
    </button>
  );
}

function InboxFilterPopover({
  label,
  value,
  icon,
  active,
  children,
}: {
  label: string;
  value: string;
  icon?: ReactNode;
  active?: boolean;
  children: ReactNode;
}) {
  return (
    <Popover>
      <PopoverTrigger
        render={
          // Quiet at rest: an unused filter is a muted, borderless chip showing
          // its category (e.g. "Source"). Once active it gains a solid border
          // and its selected value, so the bar only draws attention to filters
          // actually in use.
          <button
            type="button"
            aria-label={`${label}: ${value}`}
            className={`flex h-8 shrink-0 items-center gap-1.5 rounded-(--radius-2) border px-2.5 transition-colors focus-visible:outline-none ${
              active
                ? "border-border bg-(--color-panel-solid) text-gray-12 hover:border-(--gray-6) hover:bg-(--gray-2)"
                : "border-transparent text-gray-10 hover:border-(--gray-6) hover:bg-(--gray-2) hover:text-gray-12"
            }`}
          >
            <span className="flex shrink-0 items-center">{icon}</span>
            <span className="max-w-[150px] truncate text-[12.5px]">
              {active ? value : label}
            </span>
            <CaretDownIcon size={10} className="shrink-0 text-(--gray-9)" />
          </button>
        }
      />
      <PopoverContent
        side="bottom"
        align="start"
        className="min-w-[220px] p-1.5"
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}
