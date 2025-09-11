import { useValues } from 'kea'

import { IconDashboard } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconWithCount } from 'lib/lemon-ui/icons'

import { dashboardsModel } from '~/models/dashboardsModel'
import { QueryBasedInsightModel } from '~/types'

interface SaveToDashboardProps {
    insight: Partial<QueryBasedInsightModel>
    setOpenModal: (open: boolean) => void
}

export function AddToDashboard({ insight, setOpenModal }: SaveToDashboardProps): JSX.Element | null {
    const { rawDashboards } = useValues(dashboardsModel)
    const dashboards = insight.dashboard_tiles?.map((tile) => rawDashboards[tile.dashboard_id]).filter((d) => !!d) || []

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
