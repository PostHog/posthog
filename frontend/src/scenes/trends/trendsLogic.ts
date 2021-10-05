import { kea } from 'kea'

import api from 'lib/api'
import { objectsEqual, toParams as toAPIParams } from 'lib/utils'
import { actionsModel } from '~/models/actionsModel'
import { ACTIONS_LINE_GRAPH_CUMULATIVE } from 'lib/constants'
import { insightLogic } from '../insights/insightLogic'
import { insightHistoryLogic } from '../insights/InsightHistoryPanel/insightHistoryLogic'
import {
    ActionFilter,
    EntityTypes,
    FilterType,
    PropertyFilter,
    SharedInsightLogicProps,
    TrendResult,
    ViewType,
} from '~/types'
import { trendsLogicType } from './trendsLogicType'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { getDefaultEventName } from 'lib/utils/getAppContext'
import { IndexedTrendResult } from 'scenes/trends/types'
import { filterTrendsClientSideParams } from 'scenes/cleanFilters'

interface PeopleParamType {
    action: ActionFilter | 'session'
    label: string
    date_to?: string | number
    date_from?: string | number
    breakdown_value?: string | number
    target_date?: number | string
    lifecycle_type?: string | number
}

export function parsePeopleParams(peopleParams: PeopleParamType, filters: Partial<FilterType>): string {
    const { action, date_from, date_to, breakdown_value, ...restParams } = peopleParams
    const params = filterTrendsClientSideParams({
        ...filters,
        entity_id: (action !== 'session' && action.id) || filters?.events?.[0]?.id || filters?.actions?.[0]?.id,
        entity_type: (action !== 'session' && action.type) || filters?.events?.[0]?.type || filters?.actions?.[0]?.type,
        entity_math: (action !== 'session' && action.math) || undefined,
        breakdown_value,
    })

    // casting here is not the best
    if (filters.insight === ViewType.STICKINESS) {
        params.stickiness_days = date_from as number
    } else if (params.display === ACTIONS_LINE_GRAPH_CUMULATIVE) {
        params.date_to = date_from as string
    } else if (filters.insight === ViewType.LIFECYCLE) {
        params.date_from = filters.date_from
        params.date_to = filters.date_to
    } else {
        params.date_from = date_from as string
        params.date_to = date_to as string
    }

    // If breakdown type is cohort, we use breakdown_value
    // If breakdown type is event, we just set another filter
    if (breakdown_value && filters.breakdown_type != 'cohort' && filters.breakdown_type != 'person') {
        params.properties = [
            ...(params.properties || []),
            { key: params.breakdown, value: breakdown_value, type: 'event' } as PropertyFilter,
        ]
    }
    if (action !== 'session' && action.properties) {
        params.properties = [...(params.properties || []), ...action.properties]
    }

    return toAPIParams({ ...params, ...restParams })
}

export function getDefaultTrendsFilters(currentFilters: Partial<FilterType>): Partial<FilterType> {
    if (!currentFilters.actions?.length && !currentFilters.events?.length) {
        const event = getDefaultEventName()

        const defaultFilters = {
            [EntityTypes.EVENTS]: [
                {
                    id: event,
                    name: event,
                    type: EntityTypes.EVENTS,
                    order: 0,
                },
            ],
        }
        return defaultFilters
    }
    return {}
}

export const trendsLogic = kea<trendsLogicType>({
    props: {} as SharedInsightLogicProps,

    key: (props) => {
        return props.dashboardItemId || 'all_trends'
    },

    connect: (props: SharedInsightLogicProps) => ({
        actions: [
            insightHistoryLogic,
            ['createInsight'],
            insightLogic({ id: props.dashboardItemId || 'new' }),
            [
                'updateInsightFilters',
                'setFilters',
                'startQuery',
                'endQuery',
                'abortQuery',
                'setFilters',
                'loadResults',
                'loadResultsSuccess',
                'setCachedResultsSuccess',
            ],
        ],
        values: [
            insightLogic({ id: props.dashboardItemId || 'new' }),
            ['filters', 'insight', 'results as insightResults', 'resultsLoading'],
            actionsModel,
            ['actions'],
        ],
    }),

    actions: () => ({
        setFilters: (filters, mergeFilters = true) => ({ filters, mergeFilters }),
        setDisplay: (display) => ({ display }),
        toggleVisibility: (index: number) => ({ index }),
        setVisibilityById: (entry: Record<number, boolean>) => ({ entry }),
        loadMoreBreakdownValues: true,
        setBreakdownValuesLoading: (loading: boolean) => ({ loading }),
        toggleLifecycle: (lifecycleName: string) => ({ lifecycleName }),
        setCachedResults: (filters: Partial<FilterType>, results: TrendResult[]) => ({ filters, results }),
    }),

    reducers: {
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
        visibilityMap: [
            {} as Record<number, any>,
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
                loadResultsSuccess: (_, { insight }) =>
                    Object.fromEntries((insight.result as TrendResult[]).map((__, i) => [i, true])),
                setCachedResultsSuccess: (_, { insight }) =>
                    Object.fromEntries(insight.result.map((__, i) => [i, true])),
            },
        ],
        breakdownValuesLoading: [
            false,
            {
                setBreakdownValuesLoading: (_, { loading }) => loading,
            },
        ],
    },

    selectors: () => ({
        results: [(s) => [s.insightResults], (results): TrendResult[] => (results || []) as TrendResult[]],
        loadMoreBreakdownUrl: [(s) => [s.insight], (insight) => insight.next],
        numberOfSeries: [
            (selectors) => [selectors.filters],
            (filters): number => (filters.events?.length || 0) + (filters.actions?.length || 0),
        ],
        indexedResults: [
            (s) => [s.filters, s.results, s.toggledLifecycles],
            (filters, _results, toggledLifecycles): IndexedTrendResult[] => {
                let results = _results || []
                if (filters.insight === ViewType.LIFECYCLE) {
                    results = results.filter((result) => toggledLifecycles.includes(String(result.status)))
                }
                console.log({ results })
                return results.map((result, index) => ({ ...result, id: index }))
            },
        ],
    }),

    listeners: ({ actions, values }) => ({
        setDisplay: async ({ display }) => {
            actions.setFilters({ display })
        },
        loadMoreBreakdownValues: async () => {
            if (!values.loadMoreBreakdownUrl) {
                return
            }
            actions.setBreakdownValuesLoading(true)

            const { filters } = values
            const response = await api.get(values.loadMoreBreakdownUrl)
            actions.loadResultsSuccess({
                result: [...values.results, ...(response.result ? response.result : [])],
                filters: filters,
                next: response.next,
            })
            actions.setBreakdownValuesLoading(false)
        },
        [eventDefinitionsModel.actionTypes.loadEventDefinitionsSuccess]: async () => {
            const newFilter = getDefaultTrendsFilters(values.filters)
            const mergedFilter: Partial<FilterType> = {
                ...values.filters,
                ...newFilter,
            }
            if (!objectsEqual(values.filters, mergedFilter)) {
                actions.setFilters(mergedFilter, true)
            }
        },
    }),
})
