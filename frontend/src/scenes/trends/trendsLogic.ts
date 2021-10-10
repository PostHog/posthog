import { kea } from 'kea'

import api from 'lib/api'
import { objectsEqual, toParams as toAPIParams, uuid } from 'lib/utils'
import { actionsModel } from '~/models/actionsModel'
import { ACTIONS_LINE_GRAPH_CUMULATIVE } from 'lib/constants'
import { insightLogic } from '../insights/insightLogic'
import { ActionFilter, InsightLogicProps, FilterType, PropertyFilter, TrendResult, ViewType } from '~/types'
import { trendsLogicType } from './trendsLogicType'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { sceneLogic } from 'scenes/sceneLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { IndexedTrendResult, TrendResponse } from 'scenes/trends/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'

interface PeopleParamType {
    action: ActionFilter | 'session'
    label: string
    date_to?: string | number
    date_from?: string | number
    breakdown_value?: string | number
    target_date?: number | string
    lifecycle_type?: string | number
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

export const trendsLogic = kea<trendsLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('all_trends'),

    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters'], actionsModel, ['actions']], // TODO: is this "actions" used?
    }),

    actions: () => ({
        setFilters: (filters: Partial<FilterType>, mergeFilters = true) => ({ filters, mergeFilters }),
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
                const dashboardItemId = props.dashboardItemId
                insightLogic(props).actions.startQuery(queryId)
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
                    } else if ((values.filters?.insight as ViewType) !== 'HISTORY') {
                        response = await api.get(
                            'api/insight/trend/?' +
                                (refresh ? 'refresh=true&' : '') +
                                toAPIParams(filterClientSideParams(values.filters)),
                            cache.abortController.signal
                        )
                    }
                } catch (e) {
                    if (e.name === 'AbortError') {
                        insightLogic(props).actions.abortQuery(
                            queryId,
                            (values.filters.insight as ViewType) || ViewType.TRENDS,
                            scene,
                            e
                        )
                    }
                    breakpoint()
                    cache.abortController = null
                    insightLogic(props).actions.endQuery(
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
                insightLogic(props).actions.endQuery(
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
    },

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
        // <insightLogic requirements>
        setFilters: async ({ filters, mergeFilters }) => {
            insightLogic(props).actions.setFilters(mergeFilters ? { ...values.filters, ...filters } : filters)
        },
        [insightLogic(props).actionTypes.setFilters]: () => {
            actions.loadResults()
        },
        setCachedResultsSuccess: () => {
            insightLogic(props).actions.fetchedResults(values.filters)
        },
        loadResultsSuccess: async () => {
            insightLogic(props).actions.fetchedResults(values.filters)
        },
        // </insightLogic requirements>
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
            actions.loadResultsSuccess({
                result: [...values.results, ...(response.result ? response.result : [])],
                filters: filters,
                next: response.next,
            })
            actions.setBreakdownValuesLoading(false)
        },
        [eventDefinitionsModel.actionTypes.loadEventDefinitionsSuccess]: async () => {
            const newFilter = cleanFilters(values.filters)
            const mergedFilter: Partial<FilterType> = {
                ...values.filters,
                ...newFilter,
            }
            if (!objectsEqual(values.filters, mergedFilter)) {
                insightLogic(props).actions.setFilters(mergedFilter)
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
})
