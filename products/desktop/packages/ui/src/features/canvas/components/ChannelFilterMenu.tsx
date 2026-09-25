import { FunnelSimple as FunnelSimpleIcon } from "@phosphor-icons/react";
import {
  ANY_SOURCE,
  type AttentionFilter,
  type ChannelItemFilters,
  type ChannelItemGrouping,
  type ChannelItemSort,
  type CreatedByFilter,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  DESKTOP_SOURCE,
  type EnvironmentFilter,
  type KindFilter,
  type PinnedFilter,
  type SourceFilter,
  sameSources,
  toggleSource,
} from "@posthog/core/canvas/channelItems";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuCheckboxItem,
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
const KIND_OPTIONS: readonly Option<KindFilter>[] = [
  { value: "any", label: "Sessions and canvases" },
  { value: "task", label: "Sessions" },
  { value: "canvas", label: "Canvases" },
];

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

const DEFAULT_GROUPINGS: readonly ChannelItemGrouping[] = [
  "date",
  "repository",
];

const GROUPING_LABELS: Record<ChannelItemGrouping, string> = {
  date: "Date",
  repository: "Repository",
  space: "Space",
};

const SORT_OPTIONS: readonly Option<ChannelItemSort>[] = [
  { value: "recent", label: "Recent activity" },
  { value: "created", label: "Date created" },
  { value: "alpha", label: "Name" },
];

const SOURCE_LABELS: Record<string, string> = {
  [DESKTOP_SOURCE]: "Desktop",
  hogdesk: "HogDesk",
  mcp_analytics: "MCP analytics",
  posthog_ai: "PostHog AI",
  posthog_code: "PostHog Desktop",
  review_hog: "ReviewHog",
};

function sourceLabel(source: string): string {
  const known = getOriginProductMeta(source)?.label ?? SOURCE_LABELS[source];
  if (known) return known;

  const words = source.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

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
  defaultValue = options[0]?.value,
  onChange,
}: {
  label: string;
  options: readonly Option<T>[];
  value: T;
  /** The value the list starts with. The trigger highlights any other value. */
  defaultValue?: T;
  onChange: (value: T) => void;
}) {
  // A list can start narrowed, so its first option is not always its default.
  // A highlighted default looks like a filter the person set and must clear.
  const narrowed = value !== defaultValue;

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

function sourcesLabel(
  options: readonly Option<string>[],
  value: SourceFilter,
): string {
  if (value.length === 0) return "Any source";
  if (value.length > 2) return `${value.length} sources`;
  return options
    .filter((option) => value.includes(option.value))
    .map((option) => option.label)
    .join(", ");
}

function SourceSubmenu({
  options,
  value,
  defaultValue,
  onChange,
}: {
  options: readonly Option<string>[];
  value: SourceFilter;
  defaultValue: SourceFilter;
  onChange: (value: SourceFilter) => void;
}) {
  const narrowed = !sameSources(value, defaultValue);

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger className="pr-1">
        <span>Source</span>
        <span
          className={`flex-1 pl-4 text-right ${narrowed ? "text-primary" : "text-muted-foreground/80"}`}
        >
          {sourcesLabel(options, value)}
        </span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuCheckboxItem
          checked={value.length === 0}
          closeOnClick={false}
          onCheckedChange={() => onChange(ANY_SOURCE)}
        >
          Any source
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        {options.map((option) => (
          <DropdownMenuCheckboxItem
            key={option.value}
            checked={value.includes(option.value)}
            closeOnClick={false}
            onCheckedChange={() => onChange(toggleSource(value, option.value))}
          >
            {option.label}
          </DropdownMenuCheckboxItem>
        ))}
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
  defaultFilters = DEFAULT_CHANNEL_ITEM_FILTERS,
  sort,
  onSortChange,
  grouping,
  groupings,
  onGroupingChange,
  onEditAppearance,
  sources,
  showCreatedBy,
  showKindFilter = false,
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
  /** What "Clear filters" restores. A value that matches it is not highlighted. */
  defaultFilters?: ChannelItemFilters;
  sort: ChannelItemSort;
  onSortChange: (sort: ChannelItemSort) => void;
  /** What the list's section headers stand for. */
  grouping: ChannelItemGrouping;
  onGroupingChange: (grouping: ChannelItemGrouping) => void;
  groupings?: readonly ChannelItemGrouping[];
  /** Opens the list's appearance dialog, which the list itself renders. */
  onEditAppearance?: () => void;
  /** `origin_product` keys present in the list. */
  sources: readonly string[];
  /** False in #me, where every session is yours and the filter says nothing. */
  showCreatedBy: boolean;
  /** False on the canvases tab: a canvas has no run to ask these about. */
  showRunFilters: boolean;
  showKindFilter?: boolean;
  /** A filter is narrowing the list, so the button says so. */
  active: boolean;
}) {
  const groupingOptions: Option<ChannelItemGrouping>[] = (
    groupings ?? (showRunFilters ? DEFAULT_GROUPINGS : [])
  ).map((value) => ({ value, label: GROUPING_LABELS[value] }));

  const sourceOptions: Option<string>[] = Array.from(
    new Set([DESKTOP_SOURCE, ...sources]),
  ).map((source) => ({
    value: source,
    label: sourceLabel(source),
  }));

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
            <FunnelSimpleIcon size={14} />
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
        {groupingOptions.length > 1 && (
          <FilterSubmenu
            label="Group by"
            options={groupingOptions}
            value={grouping}
            onChange={onGroupingChange}
          />
        )}
        <FilterSubmenu
          label="Sort by"
          options={SORT_OPTIONS}
          value={sort}
          onChange={onSortChange}
        />
        <DropdownMenuSeparator />

        {showKindFilter && (
          <FilterSubmenu
            label="Type"
            options={KIND_OPTIONS}
            value={filters.kind}
            defaultValue={defaultFilters.kind}
            onChange={(value) => onFilterChange("kind", value)}
          />
        )}
        {showRunFilters && (
          <FilterSubmenu
            label="Status"
            options={ATTENTION_OPTIONS}
            value={filters.attention}
            defaultValue={defaultFilters.attention}
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
            defaultValue={defaultFilters.createdBy}
            onChange={(value) => onFilterChange("createdBy", value)}
          />
        )}
        <FilterSubmenu
          label="Pinned"
          options={PINNED_OPTIONS}
          value={filters.pinned}
          defaultValue={defaultFilters.pinned}
          onChange={(value) => onFilterChange("pinned", value)}
        />
        {showRunFilters && (
          <>
            <FilterSubmenu
              label="Environment"
              options={ENVIRONMENT_OPTIONS}
              value={filters.environment}
              defaultValue={defaultFilters.environment}
              onChange={(value) => onFilterChange("environment", value)}
            />
            <SourceSubmenu
              options={sourceOptions}
              value={filters.sources}
              defaultValue={defaultFilters.sources}
              onChange={(value) => onFilterChange("sources", value)}
            />
          </>
        )}

        {showRunFilters && onEditAppearance && (
          <>
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
