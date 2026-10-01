import { useActions, useValues } from 'kea'

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

import { TodayFilterMenuTrigger } from './TodayFilterMenuTrigger'
import { DEFAULT_RECENT_FILTERS, RECENT_CREATED_BY_OPTIONS } from './todayRecentFilters'
import {
    DEFAULT_RECENT_GROUPING,
    DEFAULT_RECENT_SORT,
    RECENT_GROUPING_OPTIONS,
    RECENT_SORT_OPTIONS,
} from './todayRecentOrder'
import { TodayRecentRadioSubmenu } from './TodayRecentRadioSubmenu'
import { TodayRecentSourceSubmenu } from './TodayRecentSourceSubmenu'
import { todaySpacesLogic } from './todaySpacesLogic'

export function TodayRecentFilterMenu(): JSX.Element {
    const {
        recentFilters: filters,
        recentFiltersActive: active,
        recentSourceOptions,
        recentSort,
        recentGrouping,
    } = useValues(todaySpacesLogic)
    const { setRecentFilters, clearRecentFilters, setRecentSort, setRecentGrouping } = useActions(todaySpacesLogic)

    return (
        <DropdownMenu>
            <TodayFilterMenuTrigger active={active} dataAttr="today-recent-filter" />
            <DropdownMenuContent align="end" className="min-w-56">
                <TodayRecentRadioSubmenu
                    label="Group by"
                    options={RECENT_GROUPING_OPTIONS}
                    value={recentGrouping}
                    defaultValue={DEFAULT_RECENT_GROUPING}
                    onChange={setRecentGrouping}
                    dataAttr="today-recent-group-by"
                />
                <TodayRecentRadioSubmenu
                    label="Sort by"
                    options={RECENT_SORT_OPTIONS}
                    value={recentSort}
                    defaultValue={DEFAULT_RECENT_SORT}
                    onChange={setRecentSort}
                    dataAttr="today-recent-sort-by"
                />
                <DropdownMenuSeparator />
                <TodayRecentRadioSubmenu
                    label="Created by"
                    options={RECENT_CREATED_BY_OPTIONS}
                    value={filters.createdBy}
                    defaultValue={DEFAULT_RECENT_FILTERS.createdBy}
                    onChange={(createdBy) => setRecentFilters({ ...filters, createdBy })}
                    dataAttr="today-recent-filter-created-by"
                />
                <TodayRecentSourceSubmenu
                    selected={filters.sources}
                    options={recentSourceOptions}
                    onChange={(sources) => setRecentFilters({ ...filters, sources })}
                    dataAttr="today-recent-filter-source"
                />
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
