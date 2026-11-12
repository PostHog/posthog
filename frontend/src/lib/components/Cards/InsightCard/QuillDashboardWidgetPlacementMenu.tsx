import { useActions, useValues } from 'kea'

import {
    DropdownMenuEmpty,
    DropdownMenuFilterProvider,
    DropdownMenuGroup,
    DropdownMenuInput,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuList,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    Skeleton,
} from '@posthog/quill'

import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'

import { dashboardsModel } from '~/models/dashboardsModel'
import type { DashboardBasicType } from '~/types'

import type { TileGroupMoveOptions } from 'products/dashboards/frontend/dashboardTileSections'

interface QuillDashboardWidgetPlacementMenuProps {
    label: string
    destinations: DashboardWidgetPlacementDestination[]
    onSelect: (dashboard: DashboardBasicType) => void
    emptyDisabledReason: string
    tileGroupMoveOptions?: TileGroupMoveOptions
    onMoveToTileGroup?: (sectionKey: string | null) => void
}

export function QuillDashboardWidgetPlacementMenu({
    label,
    destinations,
    onSelect,
    emptyDisabledReason,
    tileGroupMoveOptions,
    onMoveToTileGroup,
}: QuillDashboardWidgetPlacementMenuProps): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)

    const tileGroups = tileGroupMoveOptions && onMoveToTileGroup ? tileGroupMoveOptions : null
    const hasTileGroupRows = !!tileGroups && (tileGroups.targets.length > 0 || tileGroups.canTakeOut)
    const hasDashboardRows = destinations.length > 0 || dashboardsLoading

    if (!hasTileGroupRows && !hasDashboardRows) {
        return (
            <DropdownMenuSub>
                <DropdownMenuSubTrigger disabledReason={emptyDisabledReason}>{label}</DropdownMenuSubTrigger>
            </DropdownMenuSub>
        )
    }

    return (
        <DropdownMenuFilterProvider autoHighlight>
            <DropdownMenuSub
                onOpenChange={(open) => {
                    if (open) {
                        loadDashboardsIfNeeded()
                    }
                }}
            >
                <DropdownMenuSubTrigger>{label}</DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                    {tileGroups && onMoveToTileGroup && hasTileGroupRows && (
                        <>
                            <DropdownMenuGroup>
                                <DropdownMenuLabel>Tile groups</DropdownMenuLabel>
                                {tileGroups.targets.map(({ sectionKey, label: groupLabel }) => (
                                    <DropdownMenuItem
                                        key={sectionKey}
                                        onClick={() => onMoveToTileGroup(sectionKey)}
                                        data-attr="dashboard-tile-move-to-group"
                                    >
                                        {groupLabel}
                                    </DropdownMenuItem>
                                ))}
                                {tileGroups.canTakeOut && (
                                    <DropdownMenuItem
                                        onClick={() => onMoveToTileGroup(null)}
                                        data-attr="dashboard-tile-take-out-of-group"
                                    >
                                        Take out of group
                                    </DropdownMenuItem>
                                )}
                            </DropdownMenuGroup>
                            {hasDashboardRows && <DropdownMenuSeparator />}
                        </>
                    )}
                    {dashboardsLoading ? (
                        <div className="flex flex-col gap-1 p-1" role="status" aria-label="Loading dashboards">
                            {[0, 1, 2].map((row) => (
                                <Skeleton key={row} className="h-7 w-48" />
                            ))}
                        </div>
                    ) : hasDashboardRows ? (
                        <>
                            <DropdownMenuInput
                                autoFocus
                                placeholder="Search dashboards"
                                aria-label="Search dashboards"
                            />
                            <DropdownMenuEmpty>No dashboards match this search</DropdownMenuEmpty>
                            <DropdownMenuList>
                                {destinations.map(({ dashboard, disabledReason }) => (
                                    <DropdownMenuItem
                                        key={dashboard.id}
                                        label={dashboard.name || 'Untitled'}
                                        disabled={!!disabledReason}
                                        description={disabledReason}
                                        onClick={() => onSelect(dashboard)}
                                    >
                                        {dashboard.name || <i>Untitled</i>}
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuList>
                        </>
                    ) : null}
                </DropdownMenuSubContent>
            </DropdownMenuSub>
        </DropdownMenuFilterProvider>
    )
}
