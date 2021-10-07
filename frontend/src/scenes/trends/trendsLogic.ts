import { kea } from 'kea'

import api from 'lib/api'
import { autocorrectInterval, objectsEqual, toParams as toAPIParams, uuid } from 'lib/utils'
import { actionsModel } from '~/models/actionsModel'
import { router } from 'kea-router'
import { ACTIONS_LINE_GRAPH_CUMULATIVE, ShownAsValue } from 'lib/constants'
import { defaultFilterTestAccounts, insightLogic, TRENDS_BASED_INSIGHTS } from '../insights/insightLogic'
import { insightHistoryLogic } from '../insights/InsightHistoryPanel/insightHistoryLogic'
import {
    ActionFilter,
    ChartDisplayType,
    SharedInsightLogicProps,
    EntityTypes,
    FilterType,
    PropertyFilter,
    TrendResult,
    ViewType,
} from '~/types'
import { trendsLogicType } from './trendsLogicType'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { sceneLogic } from 'scenes/sceneLogic'
import { getDefaultEventName } from 'lib/utils/getAppContext'
import { dashboardsModel } from '~/models/dashboardsModel'
import { IndexedTrendResult, TrendResponse } from 'scenes/trends/types'

interface PeopleParamType {
    action: ActionFilter | 'session'
    label: string
    date_to?: string | number
    date_from?: string | number
    breakdown_value?: string | number
    target_date?: number | string
    lifecycle_type?: string | number
}

function cleanFilters(filters: Partial<FilterType>): Partial<FilterType> {
    return {
        insight: ViewType.TRENDS,
        ...filters,
        interval: autocorrectInterval(filters),
        display:
            filters.session && filters.session === 'dist'
                ? ChartDisplayType.ActionsTable
                : filters.display || ChartDisplayType.ActionsLineGraphLinear,
        actions: Array.isArray(filters.actions) ? filters.actions : undefined,
        events: Array.isArray(filters.events) ? filters.events : undefined,
        properties: filters.properties || [],
        ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
    }
}

function filterClientSideParams(filters: Partial<FilterType>): Partial<FilterType> {
    const {
        people_day: _skip_this_one, // eslint-disable-line
        people_action: _skip_this_too, // eslint-disable-line
        stickiness_days: __and_this, // eslint-disable-line
        ...newFilters
    } = filters

    return newFilters
}

export function parsePeopleParams(peopleParams: PeopleParamType, filters: Partial<FilterType>): string {
    const { action, date_from, date_to, breakdown_value, ...restParams } = peopleParams
    const params = filterClientSideParams({
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

function getDefaultFilters(currentFilters: Partial<FilterType>): Partial<FilterType> {
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

    connect: {
        values: [actionsModel, ['actions']],
    },

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

    loaders: ({ cache, values, props }) => ({
        _results: {
            __default: {} as TrendResponse,
            setCachedResults: ({ results, filters }) => {
                return { result: results, filters }
            },
            loadResults: async (refresh = false, breakpoint) => {
                if (props.cachedResults && !refresh && objectsEqual(values.filters, props.filters)) {
                    return { result: props.cachedResults, filters: props.filters } as TrendResponse
                }

                // fetch this now, as it might be different when we report below
                const { scene } = sceneLogic.values

                // If a query is in progress, debounce before making the second query
                if (cache.abortController) {
                    await breakpoint(300)
                    cache.abortController.abort()
                }
                cache.abortController = new AbortController()

                const queryId = uuid()
                const dashboardItemId = props.dashboardItemId || props.fromDashboardItemId
                insightLogic.actions.startQuery(queryId)
                if (dashboardItemId) {
                    dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)
                }

                const { filters } = values

                let response
                try {
                    if (values.filters?.insight === ViewType.SESSIONS || values.filters?.session) {
                        response = await api.get(
                            'api/insight/session/?' +
                                (refresh ? 'refresh=true&' : '') +
                                toAPIParams(filterClientSideParams(values.filters)),
                            cache.abortController.signal
                        )
                    } else {
                        response = await api.get(
                            'api/insight/trend/?' +
                                (refresh ? 'refresh=true&' : '') +
                                toAPIParams(filterClientSideParams(values.filters)),
                            cache.abortController.signal
                        )
                    }
                } catch (e) {
                    if (e.name === 'AbortError') {
                        insightLogic.actions.abortQuery(
                            queryId,
                            (values.filters.insight as ViewType) || ViewType.TRENDS,
                            scene,
                            e
                        )
                    }
                    breakpoint()
                    cache.abortController = null
                    insightLogic.actions.endQuery(
                        queryId,
                        (values.filters.insight as ViewType) || ViewType.TRENDS,
                        null,
                        e
                    )
                    if (dashboardItemId) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)
                    }
                    return []
                }
                breakpoint()
                cache.abortController = null
                insightLogic.actions.endQuery(
                    queryId,
                    (values.filters.insight as ViewType) || ViewType.TRENDS,
                    response.last_refresh
                )
                if (dashboardItemId) {
                    dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, response.last_refresh)
                }

                return { ...response, filters }
            },
        },
    }),

    reducers: ({ props }) => ({
        filters: [
            (props.filters
                ? props.filters
                : (state: Record<string, any>) =>
                      cleanFilters(router.selectors.searchParams(state))) as Partial<FilterType>,
            {
                setFilters: (state, { filters, mergeFilters }) => {
                    const newState = state?.insight && TRENDS_BASED_INSIGHTS.includes(state.insight) ? state : {}
                    return cleanFilters({
                        ...(mergeFilters ? newState : {}),
                        ...filters,
                    })
                },
                setCachedResults: (_, { filters }) => filters,
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
                loadResultsSuccess: (_, { _results }) => Object.fromEntries(_results.result.map((__, i) => [i, true])),
                setCachedResultsSuccess: (_, { _results }) =>
                    Object.fromEntries(_results.result.map((__, i) => [i, true])),
            },
        ],
        breakdownValuesLoading: [
            false,
            {
                setBreakdownValuesLoading: (_, { loading }) => loading,
            },
        ],
    }),

    selectors: () => ({
        loadedFilters: [(selectors) => [selectors._results], (response) => response.filters],
        results: [(selectors) => [selectors._results], (response) => response.result],
        resultsLoading: [(selectors) => [selectors._resultsLoading], (_resultsLoading) => _resultsLoading],
        loadMoreBreakdownUrl: [(selectors) => [selectors._results], (response) => response.next],
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
                return results.map((result, index) => ({ ...result, id: index }))
            },
        ],
    }),

    listeners: ({ actions, values, props }) => ({
        setDisplay: async ({ display }) => {
            actions.setFilters({ display })
        },
        setFilters: async () => {
            if (!props.dashboardItemId) {
                insightLogic.actions.setAllFilters(values.filters)
            }
            actions.loadResults()
        },
        loadResultsSuccess: () => {
            if (!props.dashboardItemId) {
                if (!insightLogic.values.insight.id) {
                    insightHistoryLogic.actions.createInsight({
                        ...values.filters,
                        insight: values.filters.session ? ViewType.SESSIONS : values.filters.insight,
                    })
                } else {
                    insightLogic.actions.updateInsightFilters(values.filters)
                }
            }
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
            const newFilter = getDefaultFilters(values.filters)
            const mergedFilter: Partial<FilterType> = {
                ...values.filters,
                ...newFilter,
            }
            if (!objectsEqual(values.filters, mergedFilter)) {
                actions.setFilters(mergedFilter, true)
            }
        },
    }),

    events: ({ actions, cache, props }) => ({
        afterMount: () => {
            if (props.dashboardItemId) {
                // loadResults gets called in urlToAction for non-dashboard insights
                actions.loadResults()
            }
        },
        beforeUnmount: () => {
            cache.abortController?.abort()
        },
    }),

    actionToUrl: ({ values, props }) => ({
        setFilters: () => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }
            return ['/insights', values.filters, router.values.hashParams, { replace: true }]
        },
    }),

    urlToAction: ({ actions, values, props }) => ({
        '/insights': ({}, searchParams: Partial<FilterType>) => {
            if (props.dashboardItemId) {
                return
            }
            if (
                !searchParams.insight ||
                searchParams.insight === ViewType.TRENDS ||
                searchParams.insight === ViewType.SESSIONS ||
                searchParams.insight === ViewType.STICKINESS ||
                searchParams.insight === ViewType.LIFECYCLE
            ) {
                const cleanSearchParams = cleanFilters(searchParams)

                const keys = Object.keys(searchParams)

                if (keys.length === 0 || (!searchParams.actions && !searchParams.events)) {
                    cleanSearchParams.filter_test_accounts = defaultFilterTestAccounts()
                }

                // TODO: Deprecated; should be removed once backend is updated
                if (searchParams.insight === ViewType.STICKINESS) {
                    cleanSearchParams['shown_as'] = ShownAsValue.STICKINESS
                }
                if (searchParams.insight === ViewType.LIFECYCLE) {
                    cleanSearchParams['shown_as'] = ShownAsValue.LIFECYCLE
                }

                if (searchParams.insight === ViewType.SESSIONS && !searchParams.session) {
                    cleanSearchParams['session'] = 'avg'
                }

                if (searchParams.date_from === 'all' || searchParams.insight === ViewType.LIFECYCLE) {
                    cleanSearchParams['compare'] = false
                }

                Object.assign(cleanSearchParams, getDefaultFilters(cleanSearchParams))

                if (!objectsEqual(cleanSearchParams, values.loadedFilters)) {
                    actions.setFilters(cleanSearchParams, false)
                } else {
                    insightLogic.actions.setAllFilters(values.filters)
                }

                handleLifecycleDefault(cleanSearchParams, (params) => actions.setFilters(params, false))
            }
        },
    }),
})

const handleLifecycleDefault = (
    params: Partial<FilterType>,
    callback: (filters: Partial<FilterType>) => void
): void => {
    if (params.insight === ViewType.LIFECYCLE) {
        if (params.events?.length) {
            callback({
                ...params,
                events: [
                    {
                        ...params.events[0],
                        math: 'total',
                    },
                ],
                actions: [],
            })
        } else if (params.actions?.length) {
            callback({
                ...params,
                events: [],
                actions: [
                    {
                        ...params.actions[0],
                        math: 'total',
                    },
                ],
            })
        }
    }
}
