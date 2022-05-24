import { kea } from 'kea'
import { dayjs } from 'lib/dayjs'
import api from 'lib/api'
import { insightLogic } from '../insights/insightLogic'
import { InsightLogicProps, FilterType, InsightType, TrendResult, ActionFilter } from '~/types'
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
        values: [
            insightLogic(props),
            ['filters', 'insight', 'insightLoading', 'hiddenLegendKeys'],
            groupsModel,
            ['aggregationLabel'],
        ],
        actions: [
            insightLogic(props),
            ['loadResultsSuccess', 'toggleVisibility', 'setHiddenById'],
            personsModalLogic,
            ['loadPeople', 'loadPeopleFromUrl'],
        ],
    }),

    actions: () => ({
        setFilters: (filters: Partial<FilterType>, mergeFilters = true) => ({ filters, mergeFilters }),
        setDisplay: (display) => ({ display }),
        loadMoreBreakdownValues: true,
        setBreakdownValuesLoading: (loading: boolean) => ({ loading }),
        toggleLifecycle: (lifecycleName: string) => ({ lifecycleName }),
        setTargetAction: (action: ActionFilter) => ({ action }),
    }),

    reducers: () => ({
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
                return results.map((result, index) => ({ ...result, id: index }))
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
    },

    listeners: ({ actions, values, props }) => ({
        loadPeople: ({ peopleParams: { action } }) => {
            action && actions.setTargetAction(action)
        },
        loadPeopleFromUrl: ({ action }) => {
            action && actions.setTargetAction(action)
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
