import React from 'react'
import { useValues } from 'kea'
import { FunnelViz } from 'scenes/funnels/FunnelViz'
import { dashboardInsightLogic } from './dashboardInsightLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import './DashboardInsight.scss'
import { DashboardInsightHeader } from './DashboardInsightHeader'

export function DashboardInsight(): JSX.Element {
    const { dashboardInsight } = useValues(dashboardInsightLogic)
    const { dashboard } = useValues(dashboardLogic({ id: 5 }))
    const Element = FunnelViz
    const color = dashboardInsight?.color || 'white'

    return(
        dashboardInsight &&
        <>
            <DashboardInsightHeader dashboardInsight={dashboardInsight} dashboardName={dashboard?.name}/>

            {/* <div className="dashboard-insight-chart"> */}
                <Element
                    dashboardItemId={dashboardInsight.id}
                    filters={dashboardInsight.filters}
                    color={color}
                    theme={color === 'white' ? 'light' : 'dark'}
                    inSharedMode={false}
                />
            {/* </div> */}
        </>
    )
}