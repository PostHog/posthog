import {
    DashboardWidgetPlacementMenu,
    type DashboardWidgetPlacementDestination,
} from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import type { LemonMenuSection } from 'lib/lemon-ui/LemonMenu'

import type { DashboardBasicType, DashboardType } from '~/types'

import type { TileGroupMoveOptions } from 'products/dashboards/frontend/dashboardTileSections'

export interface DashboardWidgetPlacementMenusProps {
    /** Same list for Copy and Move (includes disabled rows with reasons, e.g. already on dashboard). */
    placementDestinations: DashboardWidgetPlacementDestination[]
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onCopyToDashboard?: (dashboard: DashboardBasicType) => void
    tileGroupMoveOptions?: TileGroupMoveOptions
    onMoveToTileGroup?: (sectionKey: string | null) => void
}

function tileGroupSection(
    { targets, canTakeOut }: TileGroupMoveOptions,
    onMoveToTileGroup: (sectionKey: string | null) => void
): LemonMenuSection {
    return {
        title: 'Tile groups',
        items: [
            ...targets.map(({ sectionKey, label }) => ({
                label,
                key: sectionKey,
                onClick: () => onMoveToTileGroup(sectionKey),
                'data-attr': 'dashboard-tile-move-to-group',
            })),
            canTakeOut && {
                label: 'Take out of group',
                key: 'take-out-of-group',
                onClick: () => onMoveToTileGroup(null),
                'data-attr': 'dashboard-tile-take-out-of-group',
            },
        ],
    }
}

/**
 * Move to / Copy to submenus (search + list) for dashboard text, button, and insight widgets.
 */
export function DashboardWidgetPlacementMenus({
    placementDestinations,
    onMoveToDashboard,
    onCopyToDashboard,
    tileGroupMoveOptions,
    onMoveToTileGroup,
}: DashboardWidgetPlacementMenusProps): JSX.Element {
    return (
        <>
            {onMoveToDashboard && (
                <DashboardWidgetPlacementMenu
                    label="Move to"
                    destinations={placementDestinations}
                    onSelect={(d) => onMoveToDashboard({ id: d.id, name: d.name })}
                    emptyDisabledReason="No dashboards you can move to"
                    leadingSections={
                        tileGroupMoveOptions && onMoveToTileGroup
                            ? [tileGroupSection(tileGroupMoveOptions, onMoveToTileGroup)]
                            : undefined
                    }
                />
            )}
            {onCopyToDashboard && (
                <DashboardWidgetPlacementMenu
                    label="Copy to"
                    destinations={placementDestinations}
                    onSelect={onCopyToDashboard}
                    emptyDisabledReason="No dashboards you can copy to"
                />
            )}
        </>
    )
}
