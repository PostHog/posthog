import {
    DashboardWidgetPlacementMenu,
    type DashboardWidgetPlacementDestination,
} from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'

import type { DashboardBasicType, DashboardType } from '~/types'

export interface DashboardWidgetPlacementMenusProps {
    /** Same list for Copy and Move (includes disabled rows with reasons, e.g. already on dashboard). */
    placementDestinations: DashboardWidgetPlacementDestination[]
    onOpen?: () => void
    loading?: boolean
    loaded?: boolean
    hasMore?: boolean
    onLoadMore?: () => void
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onCopyToDashboard?: (dashboard: DashboardBasicType) => void
}

/**
 * Move to / Copy to submenus (search + list) for dashboard text, button, and insight widgets.
 */
export function DashboardWidgetPlacementMenus({
    placementDestinations,
    onOpen,
    loading,
    loaded,
    hasMore,
    onLoadMore,
    onMoveToDashboard,
    onCopyToDashboard,
}: DashboardWidgetPlacementMenusProps): JSX.Element {
    return (
        <>
            {onMoveToDashboard && (
                <DashboardWidgetPlacementMenu
                    label="Move to"
                    destinations={placementDestinations}
                    onOpen={onOpen}
                    loading={loading}
                    loaded={loaded}
                    hasMore={hasMore}
                    onLoadMore={onLoadMore}
                    onSelect={(d) => onMoveToDashboard({ id: d.id, name: d.name })}
                    emptyDisabledReason="No dashboards you can move to"
                />
            )}
            {onCopyToDashboard && (
                <DashboardWidgetPlacementMenu
                    label="Copy to"
                    destinations={placementDestinations}
                    onOpen={onOpen}
                    loading={loading}
                    loaded={loaded}
                    hasMore={hasMore}
                    onLoadMore={onLoadMore}
                    onSelect={onCopyToDashboard}
                    emptyDisabledReason="No dashboards you can copy to"
                />
            )}
        </>
    )
}
