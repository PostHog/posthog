import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { TodayFilterMenuTrigger } from './TodayFilterMenuTrigger'
import { todayListAppearanceLogic } from './todayListAppearanceLogic'
import { DROPDOWN_PARTS, SHEET_PARTS } from './todayMenuParts'
import {
    DEFAULT_RECENT_FILTERS,
    RECENT_CREATED_BY_OPTIONS,
    RECENT_ENVIRONMENT_OPTIONS,
    RECENT_PINNED_OPTIONS,
    RECENT_STATUS_OPTIONS,
} from './todayRecentFilters'
import {
    DEFAULT_RECENT_GROUPING,
    DEFAULT_RECENT_SORT,
    RECENT_GROUPING_OPTIONS,
    RECENT_SORT_OPTIONS,
} from './todayRecentOrder'
import { TodayRecentRadioSubmenu } from './TodayRecentRadioSubmenu'
import { TodayRecentSourceSubmenu } from './TodayRecentSourceSubmenu'
import { TodaySheetMenu } from './TodaySheetMenu'
import { todayShellLogic } from './todayShellLogic'
import { todaySpacesLogic } from './todaySpacesLogic'

/**
 * Recent's sort, grouping and filters, in PostHog Desktop's order. Desktop's Type filter is left out,
 * because Recent holds no canvases.
 */
export function TodayRecentFilterMenu(): JSX.Element {
    const {
        recentFilters: filters,
        recentFiltersActive: active,
        recentSourceOptions,
        recentSort,
        recentGrouping,
    } = useValues(todaySpacesLogic)
    const { setRecentFilters, clearRecentFilters, setRecentSort, setRecentGrouping, touchMenuOpened } =
        useActions(todaySpacesLogic)
    const { openAppearanceDialog } = useActions(todayListAppearanceLogic)
    const { phoneLayout } = useValues(todayShellLogic)
    const [sheetOpen, setSheetOpen] = useState(false)

    const parts = phoneLayout ? SHEET_PARTS : DROPDOWN_PARTS
    const items = (
        <>
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
            <parts.Separator />
            <TodayRecentRadioSubmenu
                label="Status"
                options={RECENT_STATUS_OPTIONS}
                value={filters.status}
                defaultValue={DEFAULT_RECENT_FILTERS.status}
                onChange={(status) => setRecentFilters({ ...filters, status })}
                dataAttr="today-recent-filter-status"
            />
            <TodayRecentRadioSubmenu
                label="Created by"
                options={RECENT_CREATED_BY_OPTIONS}
                value={filters.createdBy}
                defaultValue={DEFAULT_RECENT_FILTERS.createdBy}
                onChange={(createdBy) => setRecentFilters({ ...filters, createdBy })}
                dataAttr="today-recent-filter-created-by"
            />
            <TodayRecentRadioSubmenu
                label="Pinned"
                options={RECENT_PINNED_OPTIONS}
                value={filters.pinned}
                defaultValue={DEFAULT_RECENT_FILTERS.pinned}
                onChange={(pinned) => setRecentFilters({ ...filters, pinned })}
                dataAttr="today-recent-filter-pinned"
            />
            <TodayRecentRadioSubmenu
                label="Environment"
                options={RECENT_ENVIRONMENT_OPTIONS}
                value={filters.environment}
                defaultValue={DEFAULT_RECENT_FILTERS.environment}
                onChange={(environment) => setRecentFilters({ ...filters, environment })}
                dataAttr="today-recent-filter-environment"
            />
            <TodayRecentSourceSubmenu
                selected={filters.sources}
                options={recentSourceOptions}
                onChange={(sources) => setRecentFilters({ ...filters, sources })}
                dataAttr="today-recent-filter-source"
            />
            <parts.Separator />
            <parts.Item onClick={openAppearanceDialog} dataAttr="today-recent-filter-appearance">
                Edit list item appearance…
            </parts.Item>
            {active && (
                <>
                    <parts.Separator />
                    <parts.Item variant="destructive" onClick={clearRecentFilters} dataAttr="today-recent-filter-clear">
                        Clear filters
                    </parts.Item>
                </>
            )}
        </>
    )

    if (phoneLayout) {
        const label = active ? 'Filters on' : 'Filter'
        return (
            <>
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon-lg"
                                aria-label={label}
                                className={cn(
                                    'relative text-muted-foreground',
                                    active && 'bg-fill-selected text-foreground'
                                )}
                                onClick={() => {
                                    setSheetOpen(true)
                                    touchMenuOpened('filter')
                                }}
                                data-attr="today-recent-filter"
                            />
                        }
                    >
                        <IconFilter />
                        {active && (
                            <span aria-hidden className="absolute top-1 right-1 size-1.5 rounded-full bg-primary" />
                        )}
                    </TooltipTrigger>
                    <TooltipContent>{label}</TooltipContent>
                </Tooltip>
                <TodaySheetMenu open={sheetOpen} onOpenChange={setSheetOpen} title="Filter recent sessions">
                    {items}
                </TodaySheetMenu>
            </>
        )
    }

    return (
        <DropdownMenu>
            <TodayFilterMenuTrigger active={active} dataAttr="today-recent-filter" />
            <DropdownMenuContent align="end" className="min-w-56">
                {items}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
