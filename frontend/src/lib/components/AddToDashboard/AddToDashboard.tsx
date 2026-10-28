import { useValues } from 'kea'

import { IconDashboard } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { liveDashboardIds } from 'scenes/dashboard/liveDashboardIds'

import { dashboardsModel } from '~/models/dashboardsModel'
import { InsightModel } from '~/types'

interface SaveToDashboardProps {
    insight: Partial<InsightModel>
    setOpenModal: (open: boolean) => void
}

export function AddToDashboard({ insight, setOpenModal }: SaveToDashboardProps): JSX.Element | null {
    const { rawDashboards } = useValues(dashboardsModel)
    const dashboards = liveDashboardIds(insight.dashboard_tiles)
        .map((dashboardId) => rawDashboards[dashboardId])
        .filter((d) => !!d)

    return (
        <span className="save-to-dashboard" data-attr="save-to-dashboard-button">
            <LemonButton
                onClick={() => setOpenModal(true)}
                type="secondary"
                icon={
                    <IconWithCount count={dashboards.length} showZero={false}>
                        <IconDashboard />
                    </IconWithCount>
                }
                tooltip={dashboards.length === 0 ? 'Add to dashboard' : 'Manage dashboards'}
            >
                Dashboards
            </LemonButton>
        </span>
    )
}
