import { useValues } from 'kea'

import { DashboardSelectionFilterStatus } from 'products/dashboards/frontend/components/DashboardSelectionFilterStatus'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'

export function BIDashboardFilterStatus({
    dashboardId,
    tileId,
}: {
    dashboardId: number
    tileId: number
}): JSX.Element | null {
    const { selection, targets } = useValues(biDashboardCrossFilterLogic({ dashboardId }))
    return selection ? (
        <DashboardSelectionFilterStatus type="bi" filtered={!!targets[tileId]} isSource={selection.tileId === tileId} />
    ) : null
}
