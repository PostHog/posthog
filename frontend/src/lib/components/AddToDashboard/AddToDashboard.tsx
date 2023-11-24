import { useValues } from 'kea'
import { IconGauge, IconWithCount } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { dashboardsModel } from '~/models/dashboardsModel'
import { InsightModel } from '~/types'

interface SaveToDashboardProps {
    insight: Partial<InsightModel>
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
                        <IconGauge />
                    </IconWithCount>
                }
            >
                {dashboards.length === 0 ? 'Add to dashboard' : 'Manage dashboards'}
            </LemonButton>
        </span>
    )
}
