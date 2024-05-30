import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import {
    BREAKDOWN_NULL_NUMERIC_LABEL,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_NUMERIC_LABEL,
    BREAKDOWN_OTHER_STRING_LABEL,
    isOtherBreakdown,
} from 'scenes/insights/utils'

import { LifecycleQuery, MathType } from '~/queries/schema'
import {
    ChartDisplayType,
    CountPerActorMathType,
    HogQLMathType,
    InsightLogicProps,
    LifecycleToggle,
    PropertyMathType,
    TrendAPIResponse,
    TrendResult,
} from '~/types'

import type { trendsDataLogicType } from './trendsDataLogicType'
import { IndexedTrendResult } from './types'

/** All math types that can result in non-whole numbers. */
const POSSIBLY_FRACTIONAL_MATH_TYPES: Set<MathType> = new Set(
    [CountPerActorMathType.Average as MathType]
        .concat(Object.values(HogQLMathType))
        .concat(Object.values(PropertyMathType))
)

export const trendsDataLogic = kea<trendsDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('all_trends')),
    path((key) => ['scenes', 'trends', 'trendsDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            [
                'querySource',
                'insightData',
                'insightDataLoading',
                'series',
                'formula',
                'display',
                'compare',
                'interval',
                'breakdownFilter',
                'showValuesOnSeries',
                'showLabelOnSeries',
                'showPercentStackView',
                'supportsPercentStackView',
                'trendsFilter',
                'lifecycleFilter',
                'isTrends',
                'isDataWarehouseSeries',
                'isLifecycle',
                'isStickiness',
                'isNonTimeSeriesDisplay',
                'isSingleSeries',
                'hasLegend',
                'showLegend',
                'vizSpecificOptions',
                'isHogQLInsight',
            ],
        ],
        actions: [insightVizDataLogic(props), ['setInsightData', 'updateInsightFilter', 'updateBreakdownFilter']],
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
                }
                return []
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
                return !!(Array.isArray(results) && results.find((r) => isOtherBreakdown(r.breakdown_value)))
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
                    indexedResults.sort((a, b) => {
                        const aValue =
                            a.breakdown_value === BREAKDOWN_OTHER_STRING_LABEL
                                ? -BREAKDOWN_OTHER_NUMERIC_LABEL
                                : a.breakdown_value === BREAKDOWN_NULL_STRING_LABEL
                                ? -BREAKDOWN_NULL_NUMERIC_LABEL
                                : a.aggregated_value
                        const bValue =
                            b.breakdown_value === BREAKDOWN_OTHER_STRING_LABEL
                                ? -BREAKDOWN_OTHER_NUMERIC_LABEL
                                : b.breakdown_value === BREAKDOWN_NULL_STRING_LABEL
                                ? -BREAKDOWN_NULL_NUMERIC_LABEL
                                : b.aggregated_value
                        return bValue - aValue
                    })
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
            (s) => [s.series, s.querySource, s.isLifecycle],
            (series, querySource, isLifecycle): 'people' | 'none' | number => {
                // Find the commonly shared aggregation group index if there is one.
                let firstAggregationGroupTypeIndex: 'people' | 'none' | number | undefined
                if (isLifecycle) {
                    firstAggregationGroupTypeIndex = (querySource as LifecycleQuery)?.aggregation_group_type_index
                } else {
                    firstAggregationGroupTypeIndex = series?.[0]?.math_group_type_index
                    if (!series?.every((eOrA) => eOrA?.math_group_type_index === firstAggregationGroupTypeIndex)) {
                        return 'none' // mixed group types
                    }
                }

                return firstAggregationGroupTypeIndex ?? 'people'
            },
        ],

        incompletenessOffsetFromEnd: [
            (s) => [s.results, s.interval],
            (results, interval) => {
                // Returns negative number of points to paint over starting from end of array
                if (results[0]?.days === undefined) {
                    return 0
                }
                const startDate = dayjs()
                    .tz('utc', true)
                    .startOf(interval ?? 'd')
                const startIndex = results[0].days.findIndex((day: string) => {
                    return dayjs(day).tz('utc', true) >= startDate
                })

                if (startIndex !== undefined && startIndex !== -1) {
                    return startIndex - results[0].days.length
                }
                return 0
            },
        ],

        pieChartVizOptions: [
            () => [() => values.vizSpecificOptions],
            (vizSpecificOptions) => vizSpecificOptions?.[ChartDisplayType.ActionsPie],
        ],

        mightContainFractionalNumbers: [
            (s) => [s.formula, s.series],
            (formula, series): boolean => {
                // Whether data points might contain fractional numbers, which involve extra display considerations,
                // such as rounding
                if (formula) {
                    return true
                }
                if (series) {
                    return series.some((s) => s.math && POSSIBLY_FRACTIONAL_MATH_TYPES.has(s.math))
                }
                return false
            },
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
