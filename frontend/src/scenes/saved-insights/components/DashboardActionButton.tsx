import { useActions, useValues } from 'kea'

import { IconMinusSmall, IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { QueryBasedInsightModel } from '~/types'

import { addSavedInsightsModalLogic } from '../addSavedInsightsModalLogic'

export function DashboardActionButton({ insight }: { insight: QueryBasedInsightModel }): JSX.Element {
    const { addInsightToDashboard, removeInsightFromDashboard } = useActions(addSavedInsightsModalLogic)
    const { dashboardUpdatesInProgress } = useValues(addSavedInsightsModalLogic)
    const { dashboard } = useValues(dashboardLogic)

    const isInDashboard = dashboard?.tiles.some((tile) => tile.insight?.id === insight.id)
    const isLoading = dashboardUpdatesInProgress[insight.id]

    return (
        <LemonButton
            type="secondary"
            status={isInDashboard ? 'danger' : 'default'}
            size="small"
            fullWidth
            loading={isLoading}
            onClick={(e) => {
                e.preventDefault()
                if (isLoading) {
                    return
                }

                isInDashboard
                    ? removeInsightFromDashboard(insight, dashboard?.id || 0)
                    : addInsightToDashboard(insight, dashboard?.id || 0)
            }}
            icon={isInDashboard ? <IconMinusSmall /> : <IconPlusSmall />}
        />
    )
}
