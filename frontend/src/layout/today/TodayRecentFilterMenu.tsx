import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import {
    Button,
    Dot,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { DEFAULT_RECENT_FILTERS, TodayRecentCreatedByFilter, recentSourceLabel } from './todayRecentFilters'
import { TodayRecentFilterSubmenu } from './TodayRecentFilterSubmenu'
import { DEFAULT_RECENT_GROUPING, DEFAULT_RECENT_SORT, TodayRecentGrouping, TodayRecentSort } from './todayRecentOrder'
import { TodayRecentRadioSubmenu } from './TodayRecentRadioSubmenu'
import { todaySpacesLogic } from './todaySpacesLogic'

const CREATED_BY_OPTIONS: { value: TodayRecentCreatedByFilter; label: string }[] = [
    { value: 'anyone', label: 'Anyone' },
    { value: 'me', label: 'Me' },
    { value: 'others', label: 'Other people' },
]

const GROUPING_OPTIONS: { value: TodayRecentGrouping; label: string }[] = [
    { value: 'date', label: 'Date' },
    { value: 'space', label: 'Space' },
    { value: 'repository', label: 'Repository' },
]

const SORT_OPTIONS: { value: TodayRecentSort; label: string }[] = [
    { value: 'recent', label: 'Recent activity' },
    { value: 'created', label: 'Date created' },
    { value: 'alpha', label: 'Name' },
]

function sourcesLabel(sources: string[]): string {
    if (!sources.length) {
        return 'Any source'
    }
    return sources.length > 2 ? `${sources.length} sources` : sources.map(recentSourceLabel).join(', ')
}

export function TodayRecentFilterMenu(): JSX.Element {
    const {
        recentFilters: filters,
        recentFiltersActive: active,
        recentSourceOptions,
        recentSort,
        recentGrouping,
    } = useValues(todaySpacesLogic)
    const { setRecentFilters, clearRecentFilters, setRecentSort, setRecentGrouping } = useActions(todaySpacesLogic)
    const label = active ? 'Filters on' : 'Filter'

    return (
        <DropdownMenu>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon-sm"
                                    aria-label={label}
                                    className={cn('relative', active && 'bg-fill-selected')}
                                    data-attr="today-recent-filter"
                                />
                            }
                        />
                    }
                >
                    <IconFilter />
                    {active && <Dot aria-hidden className="absolute top-0 right-0" />}
                </TooltipTrigger>
                <TooltipContent>{label}</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" className="min-w-56">
                <TodayRecentRadioSubmenu
                    label="Group by"
                    options={GROUPING_OPTIONS}
                    value={recentGrouping}
                    defaultValue={DEFAULT_RECENT_GROUPING}
                    onChange={setRecentGrouping}
                    dataAttr="today-recent-group-by"
                />
                <TodayRecentRadioSubmenu
                    label="Sort by"
                    options={SORT_OPTIONS}
                    value={recentSort}
                    defaultValue={DEFAULT_RECENT_SORT}
                    onChange={setRecentSort}
                    dataAttr="today-recent-sort-by"
                />
                <DropdownMenuSeparator />
                <TodayRecentRadioSubmenu
                    label="Created by"
                    options={CREATED_BY_OPTIONS}
                    value={filters.createdBy}
                    defaultValue={DEFAULT_RECENT_FILTERS.createdBy}
                    onChange={(createdBy) => setRecentFilters({ ...filters, createdBy })}
                    dataAttr="today-recent-filter-created-by"
                />
                <TodayRecentFilterSubmenu
                    label="Source"
                    value={sourcesLabel(filters.sources)}
                    narrowed={filters.sources.length > 0}
                >
                    <DropdownMenuCheckboxItem
                        checked={!filters.sources.length}
                        closeOnClick={false}
                        onCheckedChange={() => setRecentFilters({ ...filters, sources: [] })}
                        data-attr="today-recent-filter-source-any"
                    >
                        Any source
                    </DropdownMenuCheckboxItem>
                    <DropdownMenuSeparator />
                    {recentSourceOptions.map((source) => (
                        <DropdownMenuCheckboxItem
                            key={source}
                            checked={filters.sources.includes(source)}
                            closeOnClick={false}
                            onCheckedChange={(checked) =>
                                setRecentFilters({
                                    ...filters,
                                    sources: checked
                                        ? [...filters.sources, source]
                                        : filters.sources.filter((selected) => selected !== source),
                                })
                            }
                            data-attr="today-recent-filter-source"
                        >
                            {recentSourceLabel(source)}
                        </DropdownMenuCheckboxItem>
                    ))}
                </TodayRecentFilterSubmenu>
                {active && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={clearRecentFilters}
                            data-attr="today-recent-filter-clear"
                        >
                            Clear filters
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
