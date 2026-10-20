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
    /** Groups of this dashboard that Move to also offers. */
    tileGroupMoveOptions?: TileGroupMoveOptions
    onMoveToGroup?: (groupKey: string | null) => void
}

function tileGroupSection(
    options: TileGroupMoveOptions,
    onMoveToGroup: (groupKey: string | null) => void
): LemonMenuSection {
    return {
        title: 'Groups on this dashboard',
        items: [
            ...options.groups.map(({ groupKey, label }) => ({
                label,
                key: `group-${groupKey}`,
                onClick: () => onMoveToGroup(groupKey),
                'data-attr': 'dashboard-tile-move-to-group',
            })),
            options.inGroup && {
                label: 'Take out of group',
                key: 'take-out-of-group',
                onClick: () => onMoveToGroup(null),
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
    onMoveToGroup,
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
                        tileGroupMoveOptions && onMoveToGroup
                            ? [tileGroupSection(tileGroupMoveOptions, onMoveToGroup)]
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
