import React, { useState } from 'react'
import { SaveToDashboardModal } from './SaveToDashboardModal'
import { InsightModel } from '~/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { useValues } from 'kea'
import { urls } from '../../../scenes/urls'
import { LemonButton } from '../LemonButton'

interface SaveToDashboardProps {
    insight: Partial<InsightModel>
}

export function SaveToDashboard({ insight }: SaveToDashboardProps): JSX.Element {
    const [openModal, setOpenModal] = useState<boolean>(false)
    const { rawDashboards } = useValues(dashboardsModel)
    const dashboard = insight.dashboard ? rawDashboards[insight.dashboard] : null

    return (
        <span className="save-to-dashboard" data-attr="save-to-dashboard-button">
            <SaveToDashboardModal visible={openModal} closeModal={() => setOpenModal(false)} insight={insight} />
            {dashboard ? (
                <LemonButton to={urls.dashboard(dashboard.id, insight.short_id)} type="secondary" className="btn-save">
                    On dashboard: {dashboard?.name}
                </LemonButton>
            ) : (
                <LemonButton onClick={() => setOpenModal(true)} type="secondary" className="btn-save">
                    Add to dashboard
                </LemonButton>
            )}
        </span>
    )
}
