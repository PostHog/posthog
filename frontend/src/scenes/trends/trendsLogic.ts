import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { dayjs } from 'lib/dayjs'
import api from 'lib/api'
import { insightLogic } from '../insights/insightLogic'
import { InsightLogicProps, FilterType, InsightType, TrendResult, ActionFilter, ChartDisplayType } from '~/types'
import type { trendsLogicType } from './trendsLogicType'
import { IndexedTrendResult } from 'scenes/trends/types'
import { isTrendsInsight, keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { groupsModel } from '~/models/groupsModel'
import { subscriptions } from 'kea-subscriptions'
import { LemonSelectOption } from 'lib/components/LemonSelect'

function filtersToSecondAxisSeriesOptions(
    filters: Partial<FilterType>,
    state: LemonSelectOption<number | null>[]
): LemonSelectOption<number | null>[] {
    if (!filters || !filters.events?.length) {
        return state
    }

    const seriesAsOptions = (filters.events || []).map((eventSeries) => ({
        value: eventSeries.order,
        label: eventSeries.name,
    }))
    seriesAsOptions.push({ value: null, label: 'time series' })

    return seriesAsOptions
}

export const trendsLogic = kea<trendsLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('all_trends')),
    path((key) => ['scenes', 'trends', 'trendsLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['filters', 'insight', 'insightLoading', 'hiddenLegendKeys', 'localFilters'],
            groupsModel,
            ['aggregationLabel'],
        ],
        actions: [insightLogic(props), ['loadResultsSuccess', 'toggleVisibility', 'setHiddenById']],
    })),

    actions(() => ({
        setFilters: (filters: Partial<FilterType>, mergeFilters = true) => ({ filters, mergeFilters }),
        setDisplay: (display) => ({ display }),
        loadMoreBreakdownValues: true,
        setBreakdownValuesLoading: (loading: boolean) => ({ loading }),
        toggleLifecycle: (lifecycleName: string) => ({ lifecycleName }),
        setTargetAction: (action: ActionFilter) => ({ action }),
        setIsFormulaOn: (enabled: boolean) => ({ enabled }),
    })),

    reducers(({ props, values }) => ({
        secondAxisSeriesOptions: [
            filtersToSecondAxisSeriesOptions(values.filters, []) as LemonSelectOption<number | null>[], //index of the series to use or null for timeseries
            {
                setFilters: (state, { filters }) => filtersToSecondAxisSeriesOptions(filters, state),
            },
        ],
        toggledLifecycles: [
            ['new', 'resurrecting', 'returning', 'dormant'],
            {
                toggleLifecycle: (state, { lifecycleName }) => {
                    if (state.includes(lifecycleName)) {
                        return state.filter((lifecycles) => lifecycles !== lifecycleName)
                    }
                    return [...state, lifecycleName]
                },
            },
        ],
        targetAction: [
            {} as ActionFilter,
            {
                setTargetAction: (_, { action }) => action ?? {},
            },
        ],
        breakdownValuesLoading: [
            false,
            {
                setBreakdownValuesLoading: (_, { loading }) => loading,
            },
        ],
        isFormulaOn: [
            () => !!props.cachedInsight?.filters?.formula,
            {
                setIsFormulaOn: (_, { enabled }) => enabled,
            },
        ],
    })),

    selectors({
        loadedFilters: [
            (s) => [s.insight],
            ({ filters }): Partial<FilterType> => (isTrendsInsight(filters?.insight) ? filters ?? {} : {}),
        ],
        results: [
            (s) => [s.insight],
            ({ filters, result }): TrendResult[] =>
                isTrendsInsight(filters?.insight) && Array.isArray(result) ? result : [],
        ],
        loadMoreBreakdownUrl: [
            (s) => [s.insight],
            ({ filters, next }) => (isTrendsInsight(filters?.insight) ? next : null),
        ],
        resultsLoading: [(s) => [s.insightLoading], (insightLoading) => insightLoading],
        numberOfSeries: [
            (selectors) => [selectors.filters],
            (filters): number => (filters.events?.length || 0) + (filters.actions?.length || 0),
        ],
        indexedResults: [
            (s) => [s.filters, s.results, s.toggledLifecycles],
            (filters, _results, toggledLifecycles): IndexedTrendResult[] => {
                let results = _results || []

                if (filters.insight === InsightType.LIFECYCLE) {
                    results = results.filter((result) => toggledLifecycles.includes(String(result.status)))
                }

                if (
                    filters.display === ChartDisplayType.ActionsBarValue ||
                    filters.display === ChartDisplayType.ActionsPie
                ) {
                    results.sort((a, b) => b.aggregated_value - a.aggregated_value)
                }

                const indexedResults = results.map((result, index) => ({ ...result, id: index }))

                if (
                    filters.second_axis_series !== null &&
                    filters.second_axis_series !== undefined &&
                    filters.second_axis_series >= 0
                ) {
                    const secondAxisSeriesLabels = indexedResults[filters.second_axis_series]?.data

                    return indexedResults
                        .filter((r) => r.id !== filters.second_axis_series)
                        .map((r: IndexedTrendResult) => {
                            const buckets = secondAxisSeriesLabels.reduce((acc, label, index) => {
                                if (!acc[label]) {
                                    acc[label] = 0
                                }
                                acc[label] += r.data[index]
                                return acc
                            }, {} as Record<string, number>)
                            debugger
                            return {
                                ...r,
                                data: Object.values(buckets).map((b) => Number(b)),
                                labels: Object.keys(buckets).map((b) => b.toString()),
                            }
                        })
                }

                return indexedResults
            },
        ],
        aggregationTargetLabel: [
            (s) => [s.aggregationLabel, s.targetAction],
            (
                aggregationLabel,
                targetAction
            ): {
                singular: string
                plural: string
            } => {
                return aggregationLabel(targetAction.math_group_type_index)
            },
        ],
        incompletenessOffsetFromEnd: [
            (s) => [s.filters, s.insight],
            (filters, insight) => {
                // Returns negative number of points to paint over starting from end of array
                if (insight?.result?.[0]?.days === undefined) {
                    return 0
                }
                const startDate = dayjs().startOf(filters.interval ?? 'd')
                const startIndex = insight.result[0].days.findIndex((day: string) => dayjs(day) >= startDate)

                if (startIndex !== undefined && startIndex !== -1) {
                    return startIndex - insight.result[0].days.length
                } else {
                    return 0
                }
            },
        ],
        labelGroupType: [
            (s) => [s.filters],
            (filters): 'people' | 'none' | number => {
                // Find the commonly shared aggregation group index if there is one.
                const eventsAndActions = [...(filters.events ?? []), ...(filters.actions ?? [])]
                const firstAggregationGroupTypeIndex = eventsAndActions?.[0]?.math_group_type_index
                return eventsAndActions.every((eOrA) => eOrA?.math_group_type_index === firstAggregationGroupTypeIndex)
                    ? firstAggregationGroupTypeIndex ?? 'people' // if undefined, will resolve to 'people' label
                    : 'none' // mixed group types
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        setFilters: async ({ filters, mergeFilters }) => {
            insightLogic(props).actions.setFilters(mergeFilters ? { ...values.filters, ...filters } : filters)
        },
        setDisplay: async ({ display }) => {
            insightLogic(props).actions.setFilters({ ...values.filters, display })
        },
        loadMoreBreakdownValues: async () => {
            if (!values.loadMoreBreakdownUrl) {
                return
            }
            actions.setBreakdownValuesLoading(true)

            const { filters } = values
            const response = await api.get(values.loadMoreBreakdownUrl)
            insightLogic(props).actions.loadResultsSuccess({
                ...values.insight,
                result: [...values.results, ...(response.result ? response.result : [])],
                filters: filters,
                next: response.next,
            })
            actions.setBreakdownValuesLoading(false)
        },
        setIsFormulaOn: ({ enabled }) => {
            if (!enabled) {
                actions.setFilters({ formula: undefined })
            }
        },
    })),
    subscriptions(({ values, actions }) => ({
        filters: (filters: Partial<FilterType>) => {
            const shouldFormulaBeOn = !!filters.formula
            // Prevent too many renders by only firing the action if needed
            if (values.isFormulaOn !== shouldFormulaBeOn) {
                actions.setIsFormulaOn(shouldFormulaBeOn)
            }
        },
    })),
])
