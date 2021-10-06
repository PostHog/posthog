import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import { chartFilterLogicType } from './chartFilterLogicType'
import { ChartDisplayType, FunnelVizType, ViewType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

function isFunnelVizType(filter: FunnelVizType | ChartDisplayType): filter is FunnelVizType {
    return Object.values(FunnelVizType).includes(filter as FunnelVizType)
}

interface ChartFilterLogicProps {
    dashboardItemId?: number
}

export const chartFilterLogic = kea<chartFilterLogicType<ChartFilterLogicProps>>({
    props: {} as ChartFilterLogicProps,
    key: (props) => props.dashboardItemId || 'new',
    connect: (props: ChartFilterLogicProps) => ({
        values: [insightLogic({ id: props.dashboardItemId }), ['filters']],
        actions: [insightLogic({ id: props.dashboardItemId }), ['updateInsightFilters']],
    }),
    actions: () => ({
        setChartFilter: (filter: ChartDisplayType | FunnelVizType) => ({ filter }),
    }),
    selectors: {
        chartFilter: [
            (s) => [s.filters],
            (filters): ChartDisplayType | FunnelVizType | null => {
                const { display, insight, funnel_viz_type } = filters || {}
                if (display === ChartDisplayType.FunnelViz && !funnel_viz_type) {
                    return FunnelVizType.Steps
                } else if (display && !funnel_viz_type) {
                    return display
                } else if (insight === ViewType.RETENTION) {
                    return ChartDisplayType.ActionsTable
                } else if (insight === ViewType.FUNNELS) {
                    return (funnel_viz_type as FunnelVizType) || FunnelVizType.Steps
                }
                return null
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        setChartFilter: ({ filter }) => {
            if (!objectsEqual(filter, values.chartFilter)) {
                if (isFunnelVizType(filter)) {
                    actions.updateInsightFilters({
                        ...values.filters,
                        funnel_viz_type: filter,
                        display: ChartDisplayType.FunnelViz,
                    })
                } else {
                    actions.updateInsightFilters({ ...values.filters, display: values.chartFilter as ChartDisplayType })
                }
            }
        },
    }),
})
