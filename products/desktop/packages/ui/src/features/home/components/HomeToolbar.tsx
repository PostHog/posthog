import {
  ArrowsDownUpIcon,
  FunnelIcon,
  MagnifyingGlassIcon,
  RowsIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  HOME_GROUP_BY_LABELS,
  HOME_SORT_LABELS,
  type HomeFacets,
  type HomeGroupBy,
  type HomeSort,
} from "@posthog/core/home/homeFilters";
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@posthog/quill";
import { HomeStatusIcon } from "@posthog/ui/features/home/components/HomeStatusIcon";
import { useHomeViewStore } from "@posthog/ui/features/home/homeViewStore";

const GROUP_BY_OPTIONS: HomeGroupBy[] = [
  "status",
  "project",
  "space",
  "assignee",
  "none",
];

const SORT_OPTIONS: HomeSort[] = ["recent", "created", "alpha", "status"];

/**
 * Search, the filter menu, and how the table is arranged. One bar, so the whole
 * state of the table is readable without opening anything: the filter button
 * carries the number of filters hiding rows behind it.
 */
export function HomeToolbar({
  facets,
  activeFilterCount,
}: {
  facets: HomeFacets;
  activeFilterCount: number;
}) {
  const query = useHomeViewStore((state) => state.query);
  const setQuery = useHomeViewStore((state) => state.setQuery);
  const filters = useHomeViewStore((state) => state.filters);
  const toggleFilter = useHomeViewStore((state) => state.toggleFilter);
  const clearFilters = useHomeViewStore((state) => state.clearFilters);
  const groupBy = useHomeViewStore((state) => state.groupBy);
  const setGroupBy = useHomeViewStore((state) => state.setGroupBy);
  const sort = useHomeViewStore((state) => state.sort);
  const setSort = useHomeViewStore((state) => state.setSort);

  return (
    <div className="flex shrink-0 items-center gap-2 border-(--gray-4) border-b px-3 py-2">
      <InputGroup className="max-w-64">
        <InputGroupAddon>
          <MagnifyingGlassIcon size={14} className="text-(--gray-10)" />
        </InputGroupAddon>
        <InputGroupInput
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search work"
          aria-label="Search work"
        />
        {query ? (
          <InputGroupAddon align="inline-end">
            <Button
              variant="default"
              size="icon-xs"
              aria-label="Clear search"
              onClick={() => setQuery("")}
            >
              <XIcon size={12} />
            </Button>
          </InputGroupAddon>
        ) : null}
      </InputGroup>

      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant={activeFilterCount ? "outline" : "default"}
              size="sm"
            >
              <FunnelIcon size={14} />
              Filter
              {activeFilterCount ? (
                <span className="tabular-nums">{activeFilterCount}</span>
              ) : null}
            </Button>
          }
        />
        <DropdownMenuContent
          align="start"
          className="max-h-96 min-w-56 overflow-y-auto"
        >
          <DropdownMenuGroup>
            <DropdownMenuLabel>Status</DropdownMenuLabel>
            {facets.statuses.map((facet) => (
              <DropdownMenuCheckboxItem
                key={facet.value}
                checked={filters.statuses.includes(facet.value)}
                onCheckedChange={() => toggleFilter("statuses", facet.value)}
              >
                <HomeStatusIcon status={facet.value} size={14} />
                <span className="whitespace-nowrap">{facet.label}</span>
                <span className="ml-auto tabular-nums">{facet.count}</span>
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuGroup>

          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuLabel>Kind</DropdownMenuLabel>
            {facets.kinds.map((facet) => (
              <DropdownMenuCheckboxItem
                key={facet.value}
                checked={filters.kinds.includes(facet.value)}
                onCheckedChange={() => toggleFilter("kinds", facet.value)}
              >
                <span className="whitespace-nowrap">{facet.label}</span>
                <span className="ml-auto tabular-nums">{facet.count}</span>
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuGroup>

          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuLabel>Space</DropdownMenuLabel>
            {facets.spaces.map((facet) => (
              <DropdownMenuCheckboxItem
                key={facet.value}
                checked={filters.spaceIds.includes(facet.value)}
                onCheckedChange={() => toggleFilter("spaceIds", facet.value)}
              >
                <span className="whitespace-nowrap">{facet.label}</span>
                <span className="ml-auto tabular-nums">{facet.count}</span>
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuGroup>

          {facets.projects.length > 0 ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuLabel>Project</DropdownMenuLabel>
                {facets.projects.map((facet) => (
                  <DropdownMenuCheckboxItem
                    key={facet.value}
                    checked={filters.projectIds.includes(facet.value)}
                    onCheckedChange={() =>
                      toggleFilter("projectIds", facet.value)
                    }
                  >
                    <span className="whitespace-nowrap">{facet.label}</span>
                    <span className="ml-auto tabular-nums">{facet.count}</span>
                  </DropdownMenuCheckboxItem>
                ))}
              </DropdownMenuGroup>
            </>
          ) : null}

          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuLabel>Started by</DropdownMenuLabel>
            {facets.assignees.map((facet) => (
              <DropdownMenuCheckboxItem
                key={facet.value}
                checked={filters.assigneeUuids.includes(facet.value)}
                onCheckedChange={() =>
                  toggleFilter("assigneeUuids", facet.value)
                }
              >
                <span className="whitespace-nowrap">{facet.label}</span>
                <span className="ml-auto tabular-nums">{facet.count}</span>
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuGroup>

          {activeFilterCount > 0 ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={clearFilters}>
                Clear filters
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button variant="default" size="sm">
              <RowsIcon size={14} />
              {HOME_GROUP_BY_LABELS[groupBy]}
            </Button>
          }
        />
        <DropdownMenuContent align="start">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Group by</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={groupBy}>
              {GROUP_BY_OPTIONS.map((option) => (
                <DropdownMenuRadioItem
                  key={option}
                  value={option}
                  onClick={() => setGroupBy(option)}
                >
                  {HOME_GROUP_BY_LABELS[option]}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button variant="default" size="sm">
              <ArrowsDownUpIcon size={14} />
              {HOME_SORT_LABELS[sort]}
            </Button>
          }
        />
        <DropdownMenuContent align="start">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Sort by</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={sort}>
              {SORT_OPTIONS.map((option) => (
                <DropdownMenuRadioItem
                  key={option}
                  value={option}
                  onClick={() => setSort(option)}
                >
                  {HOME_SORT_LABELS[option]}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
