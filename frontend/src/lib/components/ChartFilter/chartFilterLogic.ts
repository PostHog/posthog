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
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export const chartFilterLogic = kea<chartFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'ChartFilter', 'chartFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [
            insightLogic(props),
            ['setFilters'],
            insightVizDataLogic(props),
            ['updateInsightFilter', 'updateBreakdown'],
        ],
        values: [
            insightLogic(props),
            ['filters'],
            insightVizDataLogic(props),
            ['isTrends', 'isStickiness', 'display', 'series'],
        ],
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

            const { isTrends, isStickiness, display, series } = values
            const newDisplay = chartFilter as ChartDisplayType

            if ((isTrends || isStickiness) && display !== newDisplay) {
                actions.updateInsightFilter({ display: newDisplay })

                // For the map, make sure we are breaking down by country
                if (isTrends && newDisplay === ChartDisplayType.WorldMap) {
                    const math = series?.[0].math
                    const math_group_type_index = series?.[0].math_group_type_index

                    actions.updateBreakdown({
                        breakdown: '$geoip_country_code',
                        breakdown_type:
                            (math === 'unique_group'
                                ? 'group'
                                : ['dau', 'weekly_active', 'monthly_active'].includes(math || '')
                                ? 'person'
                                : null) || 'event',
                        breakdown_group_type_index: math_group_type_index,
                    })
                }
            }
        },
    }),
})
