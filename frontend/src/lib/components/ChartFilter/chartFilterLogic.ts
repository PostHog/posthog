import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import type { chartFilterLogicType } from './chartFilterLogicType'
import { ChartDisplayType, InsightLogicProps, TrendsFilterType } from '~/types'
import {
    isFilterWithDisplay,
    isStickinessFilter,
    isTrendsFilter,
    keyForInsightLogicProps,
} from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { TrendsFilter, StickinessFilter } from '~/queries/schema'
import { filterForQuery, isStickinessQuery, isTrendsQuery } from '~/queries/utils'

export const chartFilterLogic = kea<chartFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'ChartFilter', 'chartFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters'], insightDataLogic(props), ['updateInsightFilter']],
        values: [insightLogic(props), ['filters'], insightDataLogic(props), ['querySource']],
    }),

    actions: () => ({
        setChartFilter: (chartFilter: ChartDisplayType) => ({ chartFilter }),
    }),

    selectors: {
        chartFilter: [
            (s) => [s.filters],
            (filters): ChartDisplayType | null => {
                return (isFilterWithDisplay(filters) ? filters.display : null) || null
            },
        ],
    },

    listeners: ({ actions, values }) => ({
        setChartFilter: ({ chartFilter }) => {
            if (isTrendsFilter(values.filters) || isStickinessFilter(values.filters)) {
                if (!objectsEqual(values.filters.display, chartFilter)) {
                    const newFilteres: Partial<TrendsFilterType> = { ...values.filters, display: chartFilter }
                    actions.setFilters(newFilteres)
                }
            }

            if (isTrendsQuery(values.querySource) || isStickinessQuery(values.querySource)) {
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
