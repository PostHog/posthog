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
    const dashboards = insight.dashboards?.map((dashboard) => rawDashboards[dashboard]).filter((d) => !!d) || []

    return (
        <span className="save-to-dashboard" data-attr="save-to-dashboard-button">
            <SaveToDashboardModal visible={openModal} closeModal={() => setOpenModal(false)} insight={insight} />
            {dashboards.length > 0 ? (
                <LemonButton
                    to={urls.dashboard(dashboards[0].id, insight.short_id)}
                    type="secondary"
                    className="btn-save"
                >
                    {dashboards.length > 1 ? 'On multiple dashboards' : `On dashboard: ${dashboards[0]?.name}`}
                </LemonButton>
            ) : (
                <LemonButton onClick={() => setOpenModal(true)} type="secondary" className="btn-save">
                    Add to dashboard
                </LemonButton>
            )}
        </span>
    )
}
