import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { insightsModel } from '~/models/insightsModel'
import { InsightLogicProps, QueryBasedInsightModel } from '~/types'

import { toggleAnnotationsInInsightQuery } from './annotationsToggle'
import { toggleDisplayLabelsInInsightQuery } from './displayLabelsToggle'
import { toggleLegendInInsightQuery } from './legendToggle'

type DashboardInsightActionsProps = {
    insight: QueryBasedInsightModel
    insightLogicProps: InsightLogicProps
    dashboardId: number | undefined
    canToggleDisplayLabels: boolean
    canToggleLegend: boolean
    canToggleAnnotations: boolean
}

/** Quick visualization toggles in the insight card ⋯ menu on dashboard (and similar placements). */
export function DashboardInsightActions({
    insight,
    insightLogicProps,
    dashboardId,
    canToggleDisplayLabels,
    canToggleLegend,
    canToggleAnnotations,
}: DashboardInsightActionsProps): JSX.Element | null {
    const {
        displayLabelsToggleTextForInsight,
        legendToggleTextForInsight,
        annotationsToggleTextForInsight,
        query: activeQuery,
    } = useValues(insightLogic(insightLogicProps))
    const { updateInsightDirect } = useActions(insightsModel)
    const {
        reportDashboardInsightValuesOnSeriesToggled,
        reportDashboardInsightLegendToggled,
        reportDashboardInsightAnnotationsToggled,
    } = useActions(eventUsageLogic)

    if (!canToggleDisplayLabels && !canToggleLegend && !canToggleAnnotations) {
        return null
    }

    return (
        <>
            <LemonDivider />
            {canToggleDisplayLabels && (
                <LemonButton
                    onClick={() => {
                        const currentQuery = activeQuery ?? insight.query
                        const query = toggleDisplayLabelsInInsightQuery(currentQuery)
                        if (query !== currentQuery) {
                            updateInsightDirect(insight, { query })
                            reportDashboardInsightValuesOnSeriesToggled(
                                dashboardId,
                                insight.id,
                                DashboardEventSource.MoreDropdown
                            )
                        }
                    }}
                    fullWidth
                >
                    {displayLabelsToggleTextForInsight}
                </LemonButton>
            )}
            {canToggleLegend && (
                <LemonButton
                    onClick={() => {
                        const currentQuery = activeQuery ?? insight.query
                        const query = toggleLegendInInsightQuery(currentQuery)
                        if (query !== currentQuery) {
                            updateInsightDirect(insight, { query })
                            reportDashboardInsightLegendToggled(
                                dashboardId,
                                insight.id,
                                DashboardEventSource.MoreDropdown
                            )
                        }
                    }}
                    fullWidth
                >
                    {legendToggleTextForInsight}
                </LemonButton>
            )}
            {canToggleAnnotations && (
                <LemonButton
                    onClick={() => {
                        const currentQuery = activeQuery ?? insight.query
                        const query = toggleAnnotationsInInsightQuery(currentQuery)
                        if (query !== currentQuery) {
                            updateInsightDirect(insight, { query })
                            reportDashboardInsightAnnotationsToggled(
                                dashboardId,
                                insight.id,
                                DashboardEventSource.MoreDropdown
                            )
                        }
                    }}
                    fullWidth
                >
                    {annotationsToggleTextForInsight}
                </LemonButton>
            )}
            <LemonDivider />
        </>
    )
}
