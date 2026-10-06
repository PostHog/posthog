import { useActions, useValues } from 'kea'

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

import { TodayFilterMenuTrigger } from './TodayFilterMenuTrigger'
import { TodayRecentRadioSubmenu } from './TodayRecentRadioSubmenu'
import { DEFAULT_VIEWS_FILTERS, VIEWS_CREATED_BY_OPTIONS, VIEWS_TYPE_OPTIONS } from './todayViewsFilters'
import { todayViewsLogic } from './todayViewsLogic'

/** The Views pane's filters for its recent list, laid out like the Spaces pane's. */
export function TodayViewsFilterMenu(): JSX.Element {
    const { recentFilters: filters, recentFiltersActive: active } = useValues(todayViewsLogic)
    const { setRecentFilters, clearRecentSearchAndFilters } = useActions(todayViewsLogic)

    return (
        <DropdownMenu>
            <TodayFilterMenuTrigger active={active} dataAttr="today-views-filter" />
            <DropdownMenuContent align="end" className="min-w-56">
                <TodayRecentRadioSubmenu
                    label="Type"
                    options={VIEWS_TYPE_OPTIONS}
                    value={filters.type}
                    defaultValue={DEFAULT_VIEWS_FILTERS.type}
                    onChange={(type) => setRecentFilters({ ...filters, type })}
                    dataAttr="today-views-filter-type"
                />
                <TodayRecentRadioSubmenu
                    label="Created by"
                    options={VIEWS_CREATED_BY_OPTIONS}
                    value={filters.createdBy}
                    defaultValue={DEFAULT_VIEWS_FILTERS.createdBy}
                    onChange={(createdBy) => setRecentFilters({ ...filters, createdBy })}
                    dataAttr="today-views-filter-created-by"
                />
                {active && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={clearRecentSearchAndFilters}
                            data-attr="today-views-filter-clear"
                        >
                            Clear filters
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
