import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import type { chartFilterLogicType } from './chartFilterLogicType'
import { ChartDisplayType, FunnelsFilterType, FunnelVizType, InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isFunnelsFilter } from 'scenes/insights/sharedUtils'

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
            (filters): ChartDisplayType | FunnelVizType | null => {
                const { display } = filters
                return (
                    (isFunnelsFilter(filters) && display === ChartDisplayType.FunnelViz
                        ? filters.funnel_viz_type
                        : display) || null
                )
            },
        ],
    },

    listeners: ({ actions, values }) => ({
        setChartFilter: ({ chartFilter }) => {
            const { display } = values.filters

            if (isFunnelVizType(chartFilter)) {
                const funnel_viz_type = isFunnelsFilter(values.filters) ? values.filters.funnel_viz_type : null
                if (funnel_viz_type !== chartFilter || display !== ChartDisplayType.FunnelViz) {
                    const newFilters: Partial<FunnelsFilterType> = {
                        ...values.filters,
                        display: ChartDisplayType.FunnelViz,
                        funnel_viz_type: chartFilter,
                    }
                    actions.setFilters(newFilters)
                }
            } else {
                if (!objectsEqual(display, chartFilter)) {
                    actions.setFilters({ ...values.filters, display: chartFilter })
                }
            }
        },
    }),
})
