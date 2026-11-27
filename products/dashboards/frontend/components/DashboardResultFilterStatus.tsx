import { useValues } from 'kea'

import { dashboardResultFilterLogic } from '../dashboardResultFilterLogic'
import { DashboardSelectionFilterStatus } from './DashboardSelectionFilterStatus'

export function DashboardResultFilterStatus({
    dashboardId,
    tileId,
}: {
    dashboardId: number
    tileId: number
}): JSX.Element | null {
    const { selection, targets } = useValues(dashboardResultFilterLogic({ dashboardId }))
    return selection ? (
        <DashboardSelectionFilterStatus
            type="insight"
            filtered={!!targets[tileId]}
            isSource={selection.tileId === tileId}
        />
    ) : null
}
