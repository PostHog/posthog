import { IconDashboard } from '@posthog/icons'
import { useValues } from 'kea'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { dashboardsModel } from '~/models/dashboardsModel'
import { InsightModel } from '~/types'

import { openAddToDashboardModal } from './AddToDashboardModal'

interface SaveToDashboardProps {
    insight: Partial<InsightModel>
}

export function AddToDashboardButton({ insight }: SaveToDashboardProps): JSX.Element | null {
    const { rawDashboards } = useValues(dashboardsModel)
    const dashboards = insight.dashboard_tiles?.map((tile) => rawDashboards[tile.dashboard_id]).filter((d) => !!d) || []

    return (
        <span className="save-to-dashboard" data-attr="save-to-dashboard-button">
            <LemonButton
                onClick={() => openAddToDashboardModal(insight)}
                type="secondary"
                icon={
                    <IconWithCount count={dashboards.length} showZero={false}>
                        <IconDashboard />
                    </IconWithCount>
                }
            >
                {dashboards.length === 0 ? 'Add to dashboard' : 'Manage dashboards'}
            </LemonButton>
        </span>
    )
}
