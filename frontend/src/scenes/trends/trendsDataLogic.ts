import { kea, props, key, path, connect, selectors, actions, reducers, listeners } from 'kea'
import { ChartDisplayType, InsightLogicProps, LifecycleToggle, TrendAPIResponse, TrendResult } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import api from 'lib/api'

import type { trendsDataLogicType } from './trendsDataLogicType'
import { IndexedTrendResult } from './types'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { dayjs } from 'lib/dayjs'

export const trendsDataLogic = kea<trendsDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('all_trends')),
    path((key) => ['scenes', 'trends', 'trendsDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            [
                'insightData',
                'insightDataLoading',
                'series',
                'formula',
                'display',
                'compare',
                'interval',
                'breakdown',
                'showValueOnSeries',
                'showPercentStackView',
                'supportsPercentStackView',
                'trendsFilter',
                'lifecycleFilter',
                'isTrends',
                'isLifecycle',
                'isStickiness',
                'isNonTimeSeriesDisplay',
                'isSingleSeries',
                'hasLegend',
            ],
        ],
        actions: [insightVizDataLogic(props), ['setInsightData', 'updateInsightFilter']],
    })),

    actions({
        loadMoreBreakdownValues: true,
        setBreakdownValuesLoading: (loading: boolean) => ({ loading }),
    }),

    reducers({
        breakdownValuesLoading: [
            false,
            {
                setBreakdownValuesLoading: (_, { loading }) => loading,
            },
        ],
    }),

    selectors({
        results: [
            (s) => [s.insightData],
            (insightData: TrendAPIResponse | null): TrendResult[] => {
                if (insightData?.result && Array.isArray(insightData.result)) {
                    return insightData.result
                } else {
                    return []
                }
            },
        ],

        loadMoreBreakdownUrl: [
            (s) => [s.insightData, s.isTrends],
            (insightData, isTrends) => {
                return isTrends ? insightData?.next : null
            },
        ],

        indexedResults: [
            (s) => [s.results, s.display, s.lifecycleFilter],
            (results, display, lifecycleFilter): IndexedTrendResult[] => {
                const defaultLifecyclesOrder = ['new', 'resurrecting', 'returning', 'dormant']
                let indexedResults = results.map((result, index) => ({ ...result, seriesIndex: index }))
                if (
                    display &&
                    (display === ChartDisplayType.ActionsBarValue || display === ChartDisplayType.ActionsPie)
                ) {
                    indexedResults.sort((a, b) => b.aggregated_value - a.aggregated_value)
                } else if (lifecycleFilter) {
                    if (lifecycleFilter.toggledLifecycles) {
                        indexedResults = indexedResults.filter((result) =>
                            lifecycleFilter.toggledLifecycles!.includes(String(result.status) as LifecycleToggle)
                        )
                    }

                    indexedResults = indexedResults.sort(
                        (a, b) =>
                            defaultLifecyclesOrder.indexOf(String(b.status)) -
                            defaultLifecyclesOrder.indexOf(String(a.status))
                    )
                }
                return indexedResults.map((result, index) => ({ ...result, id: index }))
            },
        ],

        labelGroupType: [
            (s) => [s.series],
            (series): 'people' | 'none' | number => {
                // Find the commonly shared aggregation group index if there is one.
                const firstAggregationGroupTypeIndex = series?.[0]?.math_group_type_index
                return series?.every((eOrA) => eOrA?.math_group_type_index === firstAggregationGroupTypeIndex)
                    ? firstAggregationGroupTypeIndex ?? 'people' // if undefined, will resolve to 'people' label
                    : 'none' // mixed group types
            },
        ],

        incompletenessOffsetFromEnd: [
            (s) => [s.results, s.interval],
            (results, interval) => {
                // Returns negative number of points to paint over starting from end of array
                if (results[0]?.days === undefined) {
                    return 0
                }
                const startDate = dayjs().startOf(interval ?? 'd')
                const startIndex = results[0].days.findIndex((day: string) => dayjs(day) >= startDate)

                if (startIndex !== undefined && startIndex !== -1) {
                    return startIndex - results[0].days.length
                } else {
                    return 0
                }
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadMoreBreakdownValues: async () => {
            if (!values.loadMoreBreakdownUrl) {
                return
            }
            actions.setBreakdownValuesLoading(true)

            const response = await api.get(values.loadMoreBreakdownUrl)

            actions.setInsightData({
                ...values.insightData,
                result: [...values.insightData.result, ...(response.result ? response.result : [])],
                next: response.next,
            })

            actions.setBreakdownValuesLoading(false)
        },
    })),
])
