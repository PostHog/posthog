import React, { useState } from 'react'
import { AddToDashboardModal } from './AddToDashboardModal'
import { InsightModel } from '~/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { useValues } from 'kea'
import { LemonButton } from '../LemonButton'
import { IconGauge, IconWithCount } from 'lib/components/icons'

interface SaveToDashboardProps {
    insight: Partial<InsightModel>
    canEditInsight: boolean
}

export function AddToDashboard({ insight, canEditInsight }: SaveToDashboardProps): JSX.Element {
    const [openModal, setOpenModal] = useState<boolean>(false)
    const { rawDashboards } = useValues(dashboardsModel)
    const dashboards = insight.dashboards?.map((dashboard) => rawDashboards[dashboard]).filter((d) => !!d) || []

    return (
        <span className="save-to-dashboard" data-attr="save-to-dashboard-button">
            <AddToDashboardModal
                visible={openModal}
                closeModal={() => setOpenModal(false)}
                insight={insight}
                canEditInsight={canEditInsight}
            />
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
