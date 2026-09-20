import { CardsThreeIcon, ListIcon } from "@phosphor-icons/react";
import {
  DEFAULT_CHANNEL_ITEM_FILTERS,
  hasActiveChannelItemFilters,
} from "@posthog/core/canvas/channelItems";
import {
  ToggleGroup,
  ToggleGroupItem,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ChannelFilterMenu } from "@posthog/ui/features/canvas/components/ChannelFilterMenu";
import {
  type SpaceActivityView,
  useSpaceActivityViewStore,
} from "@posthog/ui/features/canvas/stores/spaceActivityViewStore";

/** A space's log is one space, so it groups by day or by repository, never by space. */
const GROUPINGS = ["date", "repository"] as const;

const VIEWS: {
  value: SpaceActivityView;
  label: string;
  Icon: typeof ListIcon;
}[] = [
  { value: "list", label: "List", Icon: ListIcon },
  { value: "cards", label: "Cards", Icon: CardsThreeIcon },
];

/**
 * The log's controls: how a row is drawn, and which rows are drawn.
 *
 * The filter menu is the one the space lists use, so a status or a source
 * means the same thing here as it does in the column beside it.
 */
export function SpaceActivityControls({
  sources,
}: {
  /** `origin_product` keys present in the log, for the Source filter. */
  sources: readonly string[];
}) {
  const view = useSpaceActivityViewStore((s) => s.view);
  const setView = useSpaceActivityViewStore((s) => s.setView);
  const filters = useSpaceActivityViewStore((s) => s.filters);
  const setFilters = useSpaceActivityViewStore((s) => s.setFilters);
  const sort = useSpaceActivityViewStore((s) => s.sort);
  const setSort = useSpaceActivityViewStore((s) => s.setSort);
  const grouping = useSpaceActivityViewStore((s) => s.grouping);
  const setGrouping = useSpaceActivityViewStore((s) => s.setGrouping);

  return (
    <div className="flex items-center gap-1">
      <ToggleGroup
        value={[view]}
        onValueChange={(next) => {
          const picked = next[0];
          if (picked === "list" || picked === "cards") setView(picked);
        }}
      >
        {VIEWS.map(({ value, label, Icon }) => (
          <Tooltip key={value}>
            <TooltipTrigger
              render={
                <ToggleGroupItem
                  value={value}
                  size="sm"
                  aria-label={`${label} view`}
                >
                  <Icon size={14} />
                </ToggleGroupItem>
              }
            />
            <TooltipContent side="top">{label}</TooltipContent>
          </Tooltip>
        ))}
      </ToggleGroup>
      <ChannelFilterMenu
        filters={filters}
        onFilterChange={(key, value) =>
          setFilters({ ...filters, [key]: value })
        }
        onClearFilters={() => setFilters(DEFAULT_CHANNEL_ITEM_FILTERS)}
        sort={sort}
        onSortChange={setSort}
        grouping={grouping}
        onGroupingChange={setGrouping}
        groupings={GROUPINGS}
        sources={sources}
        showCreatedBy
        showRunFilters
        showKindFilter
        active={hasActiveChannelItemFilters(filters)}
      />
    </div>
  );
}
