import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { BREAKDOWN_OTHER_NUMERIC_LABEL, BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'

import { ChartDisplayType, InsightLogicProps, LifecycleToggle, TrendAPIResponse, TrendResult } from '~/types'

import type { trendsDataLogicType } from './trendsDataLogicType'
import { IndexedTrendResult } from './types'

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
                'showLabelOnSeries',
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
                'vizSpecificOptions',
            ],
        ],
        actions: [insightVizDataLogic(props), ['setInsightData', 'updateInsightFilter', 'updateBreakdown']],
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

    selectors(({ values }) => ({
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

        hasBreakdownOther: [
            (s) => [s.insightData, s.isTrends],
            (insightData, isTrends) => {
                if (!isTrends) {
                    return false
                }
                const results = insightData.result ?? insightData.results
                return !!(
                    Array.isArray(results) &&
                    results.find(
                        (r) =>
                            r.breakdown_value === BREAKDOWN_OTHER_STRING_LABEL ||
                            r.breakdown_value === BREAKDOWN_OTHER_NUMERIC_LABEL
                    )
                )
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

        pieChartVizOptions: [
            () => [() => values.vizSpecificOptions],
            (vizSpecificOptions) => vizSpecificOptions?.[ChartDisplayType.ActionsPie],
        ],
    })),

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
