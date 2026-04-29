import {
    DashboardWidgetPlacementMenu,
    type DashboardWidgetPlacementDestination,
} from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'

import type { DashboardBasicType, DashboardType } from '~/types'

export interface DashboardWidgetPlacementMenusProps {
    /** Same list for Copy and Move (includes disabled rows with reasons, e.g. already on dashboard). */
    placementDestinations: DashboardWidgetPlacementDestination[]
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onCopyToDashboard?: (dashboard: DashboardBasicType) => void
}

/**
 * Move to / Copy to submenus (search + list) for dashboard text, button, and insight widgets.
 */
export function DashboardWidgetPlacementMenus({
    placementDestinations,
    onMoveToDashboard,
    onCopyToDashboard,
}: DashboardWidgetPlacementMenusProps): JSX.Element {
    return (
        <>
            {onMoveToDashboard && (
                <DashboardWidgetPlacementMenu
                    label="Move to"
                    destinations={placementDestinations}
                    onSelect={(d) => onMoveToDashboard({ id: d.id, name: d.name })}
                    emptyDisabledReason="No dashboards you can move to"
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
