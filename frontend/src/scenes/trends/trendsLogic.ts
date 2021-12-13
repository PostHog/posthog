import { kea } from 'kea'

import api from 'lib/api'
import { insightLogic } from '../insights/insightLogic'
import { InsightLogicProps, FilterType, InsightType, TrendResult } from '~/types'
import { trendsLogicType } from './trendsLogicType'
import { IndexedTrendResult } from 'scenes/trends/types'
import { isTrendsInsight, keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { personsModalLogic } from './personsModalLogic'
import { groupsModel } from '~/models/groupsModel'

export const trendsLogic = kea<trendsLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('all_trends'),
    path: (key) => ['scenes', 'trends', 'trendsLogic', key],

    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters', 'insight', 'insightLoading'], groupsModel, ['aggregationLabel']],
        actions: [insightLogic(props), ['loadResultsSuccess'], personsModalLogic, ['loadPeople', 'loadPeopleFromUrl']],
    }),

    actions: () => ({
        setFilters: (filters: Partial<FilterType>, mergeFilters = true) => ({ filters, mergeFilters }),
        setDisplay: (display) => ({ display }),
        toggleVisibility: (index: number) => ({ index }),
        setVisibilityById: (entry: Record<number, boolean>) => ({ entry }),
        loadMoreBreakdownValues: true,
        setBreakdownValuesLoading: (loading: boolean) => ({ loading }),
        toggleLifecycle: (lifecycleName: string) => ({ lifecycleName }),
        setTargetAction: (action: Record<string, any>) => ({ action }),
    }),

    reducers: ({ props }) => ({
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
            {} as Record<string, any>,
            {
                setTargetAction: (_, { action }) => action,
            },
        ],
        visibilityMap: [
            () =>
                (Array.isArray(props.cachedResults)
                    ? Object.fromEntries(props.cachedResults.map((__, i) => [i, true]))
                    : {}) as Record<number, any>,
            {
                setVisibilityById: (
                    state: Record<number, any>,
                    {
                        entry,
                    }: {
                        entry: Record<number, any>
                    }
                ) => ({
                    ...state,
                    ...entry,
                }),
                toggleVisibility: (
                    state: Record<number, any>,
                    {
                        index,
                    }: {
                        index: number
                    }
                ) => ({
                    ...state,
                    [`${index}`]: !state[index],
                }),
                loadResultsSuccess: (state, { insight }) =>
                    Array.isArray(insight.result)
                        ? Object.fromEntries(insight.result.map((__, i) => [i, true]))
                        : state,
            },
        ],
        breakdownValuesLoading: [
            false,
            {
                setBreakdownValuesLoading: (_, { loading }) => loading,
            },
        ],
    }),

    selectors: {
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
                return results
                    .sort((a, b) => a.label.localeCompare(b.label))
                    .map((result, index) => ({ ...result, id: index }))
            },
        ],
        showModalActions: [
            (s) => [s.filters],
            (filters): boolean => {
                const isNotAggregatingByGroup = (entity: Record<string, any>): boolean =>
                    entity.math_group_type_index == undefined

                return (
                    (filters.events || []).every(isNotAggregatingByGroup) &&
                    (filters.actions || []).every(isNotAggregatingByGroup) &&
                    filters.breakdown_type !== 'group'
                )
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
    },

    listeners: ({ actions, values, props }) => ({
        loadPeople: ({ peopleParams: { action } }) => {
            actions.setTargetAction(action)
        },
        loadPeopleFromUrl: ({ action }) => {
            actions.setTargetAction(action)
        },
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
    }),
})
