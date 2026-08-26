import { FunnelSimple as FunnelSimpleIcon } from "@phosphor-icons/react";
import {
  ANY_SOURCE,
  type AttentionFilter,
  type ChannelItemFilters,
  type ChannelItemGrouping,
  type ChannelItemSort,
  type CreatedByFilter,
  type EnvironmentFilter,
  type PinnedFilter,
} from "@posthog/core/canvas/channelItems";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { cnHeaderButton } from "@posthog/ui/features/canvas/components/channelHeaderButton";
import { getOriginProductMeta } from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import {
  DOT_TONE_VAR,
  type DotTone,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";

interface Option<T extends string> {
  value: T;
  label: string;
  /** Drawn before the label, in the list's own dot colours. */
  tone?: DotTone;
}

// The two states a session can be in that are yours to clear, in the list's own
// vocabulary: blue is blocked on you, the brand yellow is output you haven't
// read. Everything settled is what's left, and has nothing to filter for.
const ATTENTION_OPTIONS: readonly Option<AttentionFilter>[] = [
  { value: "any", label: "Any status" },
  { value: "needs_input", label: "Needs input", tone: "blue" },
  { value: "unread", label: "Unread", tone: "yellow" },
];

const CREATED_BY_OPTIONS: readonly Option<CreatedByFilter>[] = [
  { value: "anyone", label: "Anyone" },
  { value: "me", label: "Me" },
  { value: "others", label: "Other people" },
];

const PINNED_OPTIONS: readonly Option<PinnedFilter>[] = [
  { value: "any", label: "All sessions" },
  { value: "pinned", label: "Pinned only" },
];

const ENVIRONMENT_OPTIONS: readonly Option<EnvironmentFilter>[] = [
  { value: "any", label: "Anywhere" },
  { value: "local", label: "Local" },
  { value: "cloud", label: "Cloud" },
];

const GROUPING_OPTIONS: readonly Option<ChannelItemGrouping>[] = [
  { value: "date", label: "Date" },
  { value: "repository", label: "Repository" },
];

const SORT_OPTIONS: readonly Option<ChannelItemSort>[] = [
  { value: "recent", label: "Recent activity" },
  { value: "created", label: "Date created" },
  { value: "alpha", label: "Name" },
];

function labelOf<T extends string>(
  options: readonly Option<T>[],
  value: T,
): string {
  return options.find((option) => option.value === value)?.label ?? "";
}

/**
 * A status option's dot, drawn from the same tone tokens a row's dot uses so the
 * menu names the marks in the list rather than a second colour vocabulary. No
 * tooltip: the label is right beside it.
 */
function OptionDot({ tone }: { tone: DotTone }) {
  return (
    <span
      aria-hidden
      className="size-2 shrink-0 rounded-full"
      style={{ backgroundColor: DOT_TONE_VAR[tone] }}
    />
  );
}

/**
 * One filter as a submenu: its name, the choice currently in force, and the
 * radio group behind it. A group per submenu keeps the top level a list of
 * questions rather than a wall of every answer to all of them.
 */
function FilterSubmenu<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly Option<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  // Every list leads with its own "everything" option, so a value that isn't the
  // first one is a choice someone made, and the trigger says so.
  const narrowed = value !== options[0]?.value;

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger className="pr-1">
        <span>{label}</span>
        <span
          className={`flex-1 pl-4 text-right ${narrowed ? "text-primary" : "text-muted-foreground/80"}`}
        >
          {labelOf(options, value)}
        </span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(next) => onChange(next as T)}
        >
          {options.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              <span className="flex items-center gap-2">
                {option.tone ? <OptionDot tone={option.tone} /> : null}
                {option.label}
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

/**
 * The sessions list's filters and sort order, behind the funnel button.
 *
 * Sources are the ones the list actually holds rather than every product that
 * can file a session: an option that can only ever empty the list is a worse
 * answer than not offering it.
 */
export function ChannelFilterMenu({
  filters,
  onFilterChange,
  onClearFilters,
  sort,
  onSortChange,
  grouping,
  onGroupingChange,
  onEditAppearance,
  sources,
  showCreatedBy,
  showRunFilters,
  active,
}: {
  /**
   * What the menu shows as chosen. It can be narrower than what is stored: a
   * filter the current list cannot answer reads as "any" here.
   */
  filters: ChannelItemFilters;
  /**
   * One field at a time. Writing the whole object back would carry the
   * narrowed values with it and drop a choice made under another tab.
   */
  onFilterChange: <K extends keyof ChannelItemFilters>(
    key: K,
    value: ChannelItemFilters[K],
  ) => void;
  onClearFilters: () => void;
  sort: ChannelItemSort;
  onSortChange: (sort: ChannelItemSort) => void;
  /** What the list's section headers stand for. */
  grouping: ChannelItemGrouping;
  onGroupingChange: (grouping: ChannelItemGrouping) => void;
  /** Opens the list's appearance dialog, which the list itself renders. */
  onEditAppearance: () => void;
  /** `origin_product` keys present in the list. */
  sources: readonly string[];
  /** False in #me, where every session is yours and the filter says nothing. */
  showCreatedBy: boolean;
  /** False on the canvases tab: a canvas has no run to ask these about. */
  showRunFilters: boolean;
  /** A filter is narrowing the list, so the button says so. */
  active: boolean;
}) {
  const sourceOptions: Option<string>[] = [
    { value: ANY_SOURCE, label: "Any source" },
    ...sources.map((source) => ({
      value: source,
      // A source we have no name for still filters — the raw key is a worse
      // label than "Slack", but a missing option would be a worse answer.
      label: getOriginProductMeta(source)?.label ?? source,
    })),
  ];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="default"
            size="icon-xs"
            aria-label="Filter"
            className={cn("relative", cnHeaderButton(active))}
          >
            <FunnelSimpleIcon size={12} />
            {active && (
              <span
                aria-hidden
                className="absolute top-0 right-0 size-1.5 rounded-full bg-primary"
              />
            )}
          </Button>
        }
      />
      <DropdownMenuContent
        align="end"
        side="bottom"
        sideOffset={6}
        className="min-w-fit"
      >
        {showRunFilters && (
          <FilterSubmenu
            label="Status"
            options={ATTENTION_OPTIONS}
            value={filters.attention}
            onChange={(value) => onFilterChange("attention", value)}
          />
        )}
        {/* #me holds only your own sessions, so "created by" can only ever
            answer "you" — the whole group is dropped rather than shown with two
            options that empty the list. */}
        {showCreatedBy && (
          <FilterSubmenu
            label="Created by"
            options={CREATED_BY_OPTIONS}
            value={filters.createdBy}
            onChange={(value) => onFilterChange("createdBy", value)}
          />
        )}
        <FilterSubmenu
          label="Pinned"
          options={PINNED_OPTIONS}
          value={filters.pinned}
          onChange={(value) => onFilterChange("pinned", value)}
        />
        {showRunFilters && (
          <>
            <FilterSubmenu
              label="Environment"
              options={ENVIRONMENT_OPTIONS}
              value={filters.environment}
              onChange={(value) => onFilterChange("environment", value)}
            />
            <FilterSubmenu
              label="Source"
              options={sourceOptions}
              value={filters.source}
              onChange={(value) => onFilterChange("source", value)}
            />
          </>
        )}
        <DropdownMenuSeparator />
        <FilterSubmenu
          label="Sort by"
          options={SORT_OPTIONS}
          value={sort}
          onChange={onSortChange}
        />
        {/* A canvas has no repository, and no second row to configure, so the
            tab that lists them is offered neither. */}
        {showRunFilters && (
          <>
            <FilterSubmenu
              label="Group by"
              options={GROUPING_OPTIONS}
              value={grouping}
              onChange={onGroupingChange}
            />
            <DropdownMenuSeparator />
            <DropdownMenuItem
              data-attr="edit-list-item-appearance"
              onClick={onEditAppearance}
            >
              Edit list item appearance…
            </DropdownMenuItem>
          </>
        )}
        {active && (
          <>
            <DropdownMenuSeparator />
            {/* The empty state tells you to clear the filters; with five of them
                behind submenus, this is where that instruction is carried out. */}
            <DropdownMenuItem onClick={onClearFilters} variant="destructive">
              Clear filters
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
