import { useState } from 'react'
import { AddToDashboardModal } from './AddToDashboardModal'
import { InsightModel } from '~/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconGauge, IconWithCount } from 'lib/lemon-ui/icons'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'

interface SaveToDashboardProps {
    insight: Partial<InsightModel>
    canEditInsight: boolean
}

export function AddToDashboard({ insight, canEditInsight }: SaveToDashboardProps): JSX.Element {
    const [openModal, setOpenModal] = useState<boolean>(false)
    const { rawDashboards } = useValues(dashboardsModel)
    const dashboards = insight.dashboard_tiles?.map((tile) => rawDashboards[tile.dashboard_id]).filter((d) => !!d) || []

    return (
        <span className="save-to-dashboard" data-attr="save-to-dashboard-button">
            <AddToDashboardModal
                isOpen={openModal}
                closeModal={() => setOpenModal(false)}
                insight={insight}
                canEditInsight={canEditInsight}
            />
            <NewDashboardModal />
            <LemonButton
                onClick={() => setOpenModal(true)}
                type="secondary"
                icon={
                    <IconWithCount count={dashboards.length} showZero={false}>
                        <IconGauge />
                    </IconWithCount>
                }
            >
                Add to dashboard
            </LemonButton>
        </span>
    )
}
