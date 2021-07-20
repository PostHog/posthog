import React from 'react'
import { useValues } from 'kea'
import { FunnelViz } from 'scenes/funnels/FunnelViz'
import { dashboardInsightLogic } from './dashboardInsightLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import './DashboardInsight.scss'
import { DashboardInsightHeader } from './DashboardInsightHeader'
import { Paths } from 'scenes/paths/Paths'
import { ActionsBarValueGraph, ActionsLineGraph, ActionsPie, ActionsTable } from 'scenes/trends/viz'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { ViewType } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Funnel } from 'scenes/funnels/Funnel'

export function DashboardInsight(): JSX.Element | null {
    const { dashboardInsight } = useValues(dashboardInsightLogic)
    const { dashboard } = useValues(dashboardLogic({ id: 5 }))
    const { featureFlags } = useValues(featureFlagLogic)

    const mapping: Record<string, any> = {
        FunnelViz: featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] ? Funnel : FunnelViz,
        PathsViz: Paths,
        ActionsLineGraph: ActionsLineGraph,
        ActionsBarValue: ActionsBarValueGraph,
        ActionsTable: ActionsTable,
        ActionsPie: ActionsPie,
    }

    const displayElement = (display: string): any => {
        return mapping[display]
    }

    let Element
    if (dashboardInsight?.insight === ViewType.RETENTION) {
        Element = RetentionContainer
    } else {
        Element = displayElement(dashboardInsight?.filters.display)
    }
    const color = dashboardInsight?.color || 'white'

    return (
        dashboardInsight && (
            <>
                <DashboardInsightHeader dashboardInsight={dashboardInsight} dashboardName={dashboard?.name} />
                <Element
                    dashboardItemId={dashboardInsight.id}
                    filters={dashboardInsight.filters}
                    color={color}
                    theme={color === 'white' ? 'light' : 'dark'}
                    inSharedMode={false}
                />
            </>
        )
    )
}
