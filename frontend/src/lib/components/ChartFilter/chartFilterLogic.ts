import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import type { chartFilterLogicType } from './chartFilterLogicType'
import { ChartDisplayType, FunnelVizType, InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'

function isFunnelVizType(filter: FunnelVizType | ChartDisplayType): filter is FunnelVizType {
    return Object.values(FunnelVizType).includes(filter as FunnelVizType)
}

export const chartFilterLogic = kea<chartFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'ChartFilter', 'chartFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters']],
        values: [insightLogic(props), ['filters']],
    }),

    actions: () => ({
        setChartFilter: (chartFilter: ChartDisplayType | FunnelVizType) => ({ chartFilter }),
    }),

    selectors: {
        chartFilter: [
            (s) => [s.filters],
            ({ display, funnel_viz_type }): ChartDisplayType | FunnelVizType | null => {
                return (display === ChartDisplayType.FunnelViz ? funnel_viz_type : display) || null
            },
        ],
    },

    listeners: ({ actions, values }) => ({
        setChartFilter: ({ chartFilter }) => {
            const { display, funnel_viz_type } = values.filters

            if (isFunnelVizType(chartFilter)) {
                if (funnel_viz_type !== chartFilter || display !== ChartDisplayType.FunnelViz) {
                    actions.setFilters({
                        ...values.filters,
                        display: ChartDisplayType.FunnelViz,
                        funnel_viz_type: chartFilter,
                    })
                }
            } else {
                if (!objectsEqual(display, chartFilter)) {
                    actions.setFilters({ ...values.filters, display: chartFilter })
                }
            }
        },
    }),
})
