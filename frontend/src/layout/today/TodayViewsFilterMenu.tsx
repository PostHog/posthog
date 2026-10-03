import { useActions, useValues } from 'kea'

import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
} from '@posthog/quill'

import { TodayFilterMenuTrigger } from './TodayFilterMenuTrigger'
import { TodayRecentRadioSubmenu } from './TodayRecentRadioSubmenu'
import {
    DEFAULT_VIEWS_FILTERS,
    VIEWS_CREATED_BY_OPTIONS,
    VIEWS_MADE_BY_OPTIONS,
    VIEWS_PINNED_OPTIONS,
    VIEWS_TYPE_OPTIONS,
} from './todayViewsFilters'
import { todayViewsLogic } from './todayViewsLogic'
import { DEFAULT_VIEWS_GROUPING, VIEWS_GROUPING_OPTIONS } from './todayViewsSections'

/** The Views pane's grouping and filters for its list, laid out like the Spaces pane's. */
export function TodayViewsFilterMenu(): JSX.Element {
    const {
        viewsFilters: filters,
        recentFiltersActive: active,
        recentGrouping,
        stackInvestigations,
    } = useValues(todayViewsLogic)
    const { setRecentFilters, setRecentGrouping, setStackInvestigations, clearRecentSearchAndFilters } =
        useActions(todayViewsLogic)

    return (
        <DropdownMenu>
            <TodayFilterMenuTrigger active={active} dataAttr="today-views-filter" />
            <DropdownMenuContent align="end" className="min-w-56">
                <TodayRecentRadioSubmenu
                    label="Group by"
                    options={VIEWS_GROUPING_OPTIONS}
                    value={recentGrouping}
                    defaultValue={DEFAULT_VIEWS_GROUPING}
                    onChange={setRecentGrouping}
                    dataAttr="today-views-group-by"
                />
                <DropdownMenuCheckboxItem
                    checked={stackInvestigations}
                    onCheckedChange={(checked) => setStackInvestigations(checked)}
                    data-attr="today-views-stack-investigations"
                >
                    Stack alert investigations
                </DropdownMenuCheckboxItem>
                <DropdownMenuSeparator />
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
                <TodayRecentRadioSubmenu
                    label="Made by"
                    options={VIEWS_MADE_BY_OPTIONS}
                    value={filters.madeBy}
                    defaultValue={DEFAULT_VIEWS_FILTERS.madeBy}
                    onChange={(madeBy) => setRecentFilters({ ...filters, madeBy })}
                    dataAttr="today-views-filter-made-by"
                />
                <TodayRecentRadioSubmenu
                    label="Pinned"
                    options={VIEWS_PINNED_OPTIONS}
                    value={filters.pinned}
                    defaultValue={DEFAULT_VIEWS_FILTERS.pinned}
                    onChange={(pinned) => setRecentFilters({ ...filters, pinned })}
                    dataAttr="today-views-filter-pinned"
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
