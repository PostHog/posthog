import { useActions } from 'kea'

import { DashboardWidgetPlacementMenu } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { dashboardsModel } from '~/models/dashboardsModel'

interface DashboardTileGroupCopyMenuProps {
    label: string
    destinations: DashboardWidgetPlacementDestination[]
    onCopyToDashboard: (dashboardId: number, dashboardName: string) => void
    loading?: boolean
}

export function DashboardTileGroupCopyMenu({
    label,
    destinations,
    onCopyToDashboard,
    loading,
}: DashboardTileGroupCopyMenuProps): JSX.Element {
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)

    return (
        <More
            data-attr="dashboard-tile-group-menu"
            tooltip="Group actions"
            loading={loading}
            disabledReason={loading ? 'Copying group' : undefined}
            dropdown={{ onVisibilityChange: (visible) => visible && loadDashboardsIfNeeded() }}
            overlay={
                <div className="min-w-48 p-1">
                    <DashboardWidgetPlacementMenu
                        label={label}
                        destinations={destinations}
                        onSelect={({ id, name }) => onCopyToDashboard(id, name || 'Untitled')}
                    />
                </div>
            }
        />
    )
}
