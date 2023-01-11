import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import type { chartFilterLogicType } from './chartFilterLogicType'
import { ChartDisplayType, FunnelsFilterType, FunnelVizType, InsightLogicProps, TrendsFilterType } from '~/types'
import {
    isFilterWithDisplay,
    isStickinessFilter,
    isTrendsFilter,
    keyForInsightLogicProps,
} from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isFunnelsFilter } from 'scenes/insights/sharedUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { TrendsFilter, StickinessFilter } from '~/queries/schema'
import { filterForQuery, isStickinessQuery, isTrendsQuery, isFunnelsQuery } from '~/queries/utils'

function isFunnelVizType(filter: FunnelVizType | ChartDisplayType): filter is FunnelVizType {
    return Object.values(FunnelVizType).includes(filter as FunnelVizType)
}

export const chartFilterLogic = kea<chartFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'ChartFilter', 'chartFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [
            insightLogic(props),
            ['setFilters'],
            insightDataLogic(props),
            ['updateQuerySource', 'updateInsightFilter'],
        ],
        values: [insightLogic(props), ['filters'], insightDataLogic(props), ['querySource']],
    }),

    actions: () => ({
        setChartFilter: (chartFilter: ChartDisplayType | FunnelVizType) => ({ chartFilter }),
    }),

    selectors: {
        chartFilter: [
            (s) => [s.filters],
            (filters): ChartDisplayType | FunnelVizType | null => {
                return (
                    (isFunnelsFilter(filters)
                        ? filters.funnel_viz_type
                        : isFilterWithDisplay(filters)
                        ? filters.display
                        : null) || null
                )
            },
        ],
    },

    listeners: ({ actions, values }) => ({
        setChartFilter: ({ chartFilter }) => {
            if (isFunnelVizType(chartFilter)) {
                const funnel_viz_type = isFunnelsFilter(values.filters) ? values.filters.funnel_viz_type : null
                if (funnel_viz_type !== chartFilter) {
                    const newFilters: Partial<FunnelsFilterType> = {
                        ...values.filters,
                        funnel_viz_type: chartFilter,
                    }
                    actions.setFilters(newFilters)
                }
            } else if (isTrendsFilter(values.filters) || isStickinessFilter(values.filters)) {
                if (!objectsEqual(values.filters.display, chartFilter)) {
                    const newFilteres: Partial<TrendsFilterType> = { ...values.filters, display: chartFilter }
                    actions.setFilters(newFilteres)
                }
            }

            if (isFunnelsQuery(values.querySource)) {
                // TODO
            } else if (isTrendsQuery(values.querySource) || isStickinessQuery(values.querySource)) {
                const currentDisplay = (
                    filterForQuery(values.querySource) as TrendsFilter | StickinessFilter | undefined
                )?.display
                if (currentDisplay !== chartFilter) {
                    actions.updateInsightFilter({ display: chartFilter as ChartDisplayType })
                }
            }
        },
    }),
})
