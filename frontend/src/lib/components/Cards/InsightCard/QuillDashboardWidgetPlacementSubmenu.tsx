import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    Input,
    Skeleton,
} from '@posthog/quill'

import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'

import { dashboardsModel } from '~/models/dashboardsModel'
import type { DashboardBasicType } from '~/types'

import type { TileGroupMoveOptions } from 'products/dashboards/frontend/dashboardTileSections'

const MENU_NAVIGATION_KEYS = new Set(['Escape', 'ArrowDown', 'ArrowUp', 'Tab'])

/** The quill "Move to" or "Copy to" submenu: tile groups first, then the dashboards with a search field. */
export function QuillDashboardWidgetPlacementSubmenu({
    label,
    destinations,
    onSelect,
    emptyDisabledReason,
    tileGroupMoveOptions,
    onMoveToTileGroup,
}: {
    label: string
    destinations: DashboardWidgetPlacementDestination[]
    onSelect: (dashboard: DashboardBasicType) => void
    emptyDisabledReason: string
    tileGroupMoveOptions?: TileGroupMoveOptions
    onMoveToTileGroup?: (sectionKey: string | null) => void
}): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)

    const showTileGroups =
        !!tileGroupMoveOptions &&
        !!onMoveToTileGroup &&
        (tileGroupMoveOptions.targets.length > 0 || tileGroupMoveOptions.canTakeOut)
    const hasDashboardItems = destinations.length > 0 || dashboardsLoading
    const filteredDestinations =
        searchTerm.trim() === ''
            ? destinations
            : destinations.filter(({ dashboard }) =>
                  (dashboard.name || 'Untitled').toLowerCase().includes(searchTerm.toLowerCase())
              )

    if (!showTileGroups && !hasDashboardItems) {
        return <DropdownMenuItem disabledReason={emptyDisabledReason}>{label}</DropdownMenuItem>
    }

    return (
        <DropdownMenuSub
            onOpenChange={(open) => {
                if (open) {
                    loadDashboardsIfNeeded()
                } else {
                    setSearchTerm('')
                }
            }}
        >
            <DropdownMenuSubTrigger>{label}</DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="max-h-96 w-64">
                {showTileGroups && (
                    <>
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Tile groups</DropdownMenuLabel>
                            {tileGroupMoveOptions.targets.map(({ sectionKey, label: groupLabel }) => (
                                <DropdownMenuItem
                                    key={sectionKey}
                                    onClick={() => onMoveToTileGroup(sectionKey)}
                                    data-attr="dashboard-tile-move-to-group"
                                >
                                    {groupLabel}
                                </DropdownMenuItem>
                            ))}
                            {tileGroupMoveOptions.canTakeOut && (
                                <DropdownMenuItem
                                    onClick={() => onMoveToTileGroup(null)}
                                    data-attr="dashboard-tile-take-out-of-group"
                                >
                                    Take out of group
                                </DropdownMenuItem>
                            )}
                        </DropdownMenuGroup>
                        {hasDashboardItems && <DropdownMenuSeparator />}
                    </>
                )}
                {hasDashboardItems && (
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Dashboards</DropdownMenuLabel>
                        <div className="px-1 pb-1">
                            <Input
                                size="sm"
                                type="search"
                                placeholder="Search dashboards"
                                aria-label="Search dashboards"
                                value={searchTerm}
                                onChange={(event) => setSearchTerm(event.target.value)}
                                // The menu reads printable keys as typeahead and would move focus off the field.
                                onKeyDown={(event) => {
                                    if (!MENU_NAVIGATION_KEYS.has(event.key)) {
                                        event.stopPropagation()
                                    }
                                }}
                            />
                        </div>
                        {dashboardsLoading ? (
                            <div className="flex flex-col gap-1 px-1">
                                <Skeleton className="h-7" />
                                <Skeleton className="h-7" />
                                <Skeleton className="h-7" />
                            </div>
                        ) : filteredDestinations.length > 0 ? (
                            filteredDestinations.map(({ dashboard, disabledReason }) => (
                                <DropdownMenuItem
                                    key={dashboard.id}
                                    disabled={!!disabledReason}
                                    description={disabledReason}
                                    onClick={() => onSelect(dashboard)}
                                >
                                    {dashboard.name || 'Untitled'}
                                </DropdownMenuItem>
                            ))
                        ) : (
                            <DropdownMenuItem disabled>No dashboards match this search</DropdownMenuItem>
                        )}
                    </DropdownMenuGroup>
                )}
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
