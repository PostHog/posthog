import { kea } from 'kea'

import api from 'lib/api'
import { autocorrectInterval, errorToast, objectsEqual, toParams as toAPIParams, uuid } from 'lib/utils'
import { toParams } from 'lib/utils'
import { actionsModel } from '~/models/actionsModel'
import { router } from 'kea-router'
import {
    ACTIONS_LINE_GRAPH_CUMULATIVE,
    ACTIONS_LINE_GRAPH_LINEAR,
    ACTIONS_TABLE,
    EVENT_TYPE,
    ACTION_TYPE,
    ShownAsValue,
} from 'lib/constants'
import { ViewType, insightLogic, defaultFilterTestAccounts, TRENDS_BASED_INSIGHTS } from '../insights/insightLogic'
import { insightHistoryLogic } from '../insights/InsightHistoryPanel/insightHistoryLogic'
import { ActionFilter, FilterType, PersonType, PropertyFilter, TrendResult, EntityTypes, PathType } from '~/types'
import { cohortLogic } from 'scenes/persons/cohortLogic'
import { trendsLogicType } from './trendsLogicType'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { cleanFunnelParams, funnelLogic } from 'scenes/funnels/funnelLogic'
interface TrendResponse {
    result: TrendResult[]
    next?: string
}

export interface IndexedTrendResult extends TrendResult {
    id: number
}

export interface TrendPeople {
    people: PersonType[]
    count: number
    day: string | number
    label: string
    action: ActionFilter | 'session'
    breakdown_value?: string
    next?: string
    loadingMore?: boolean
}

interface PeopleParamType {
    action: ActionFilter | 'session'
    label: string
    date_to?: string | number
    date_from?: string | number
    breakdown_value?: string
    target_date?: number | string
    lifecycle_type?: string
}

function cleanFilters(filters: Partial<FilterType>): Record<string, any> {
    return {
        insight: ViewType.TRENDS,
        ...filters,
        interval: autocorrectInterval(filters),
        display:
            filters.session && filters.session === 'dist'
                ? ACTIONS_TABLE
                : filters.display || ACTIONS_LINE_GRAPH_LINEAR,
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

function getDefaultFilters(currentFilters: Partial<FilterType>, eventNames: string[]): Partial<FilterType> {
    /* Opening /insights without any params, will set $pageview as the default event (or
    the first random event). We load this default events when `currentTeam` is loaded (because that's when
    `eventNames` become available) and on every view change (through the urlToAction map) */
    if (!currentFilters.actions?.length && !currentFilters.events?.length && eventNames.length) {
        const event = eventNames.includes(PathType.PageView)
            ? PathType.PageView
            : eventNames.includes(PathType.Screen)
            ? PathType.Screen
            : eventNames[0]

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

// props:
// - dashboardItemId
// - filters
export const trendsLogic = kea<trendsLogicType<IndexedTrendResult, TrendPeople, TrendResponse>>({
    key: (props) => {
        return props.dashboardItemId || 'all_trends'
    },

    connect: {
        values: [actionsModel, ['actions']],
    },

    loaders: ({ values, props }) => ({
        _results: {
            __default: {} as TrendResponse,
            loadResults: async (refresh = false, breakpoint) => {
                if (props.cachedResults && !refresh && values.filters === props.filters) {
                    return { result: props.cachedResults } as TrendResponse
                }
                const queryId = uuid()
                insightLogic.actions.startQuery(queryId)
                let response
                try {
                    if (values.filters?.insight === ViewType.SESSIONS || values.filters?.session) {
                        response = await api.get(
                            'api/insight/session/?' +
                                (refresh ? 'refresh=true&' : '') +
                                toAPIParams(filterClientSideParams(values.filters))
                        )
                    } else {
                        response = await api.get(
                            'api/insight/trend/?' +
                                (refresh ? 'refresh=true&' : '') +
                                toAPIParams(filterClientSideParams(values.filters))
                        )
                    }
                } catch (e) {
                    console.error(e)
                    breakpoint()
                    insightLogic.actions.endQuery(queryId, values.filters.insight || ViewType.TRENDS, null, e)
                    return []
                }
                breakpoint()
                insightLogic.actions.endQuery(queryId, values.filters.insight || ViewType.TRENDS, response.last_refresh)

                return response
            },
        },
    }),

    actions: () => ({
        setFilters: (filters, mergeFilters = true) => ({ filters, mergeFilters }),
        setDisplay: (display) => ({ display }),
        loadPeople: (
            action: ActionFilter | 'session', // todo, refactor this session string param out
            label: string,
            date_from: string | number,
            date_to: string | number,
            breakdown_value?: string,
            saveOriginal?: boolean,
            searchTerm?: string,
            funnelStep?: number
        ) => ({
            action,
            label,
            date_from,
            date_to,
            breakdown_value,
            saveOriginal,
            searchTerm,
            funnelStep,
        }),
        saveCohortWithFilters: (cohortName: string) => ({ cohortName }),
        loadMorePeople: true,
        refreshCohort: true,
        setLoadingMorePeople: (status) => ({ status }),
        setShowingPeople: (isShowing) => ({ isShowing }),
        setPeople: (
            people: PersonType[],
            count: number,
            action: ActionFilter | 'session',
            label: string,
            day: string | number,
            breakdown_value?: string,
            next?: string
        ) => ({
            people,
            count,
            action,
            label,
            day,
            breakdown_value,
            next,
        }),
        setIndexedResults: (results: IndexedTrendResult[]) => ({ results }),
        toggleVisibility: (index: number) => ({ index }),
        setVisibilityById: (entry: Record<number, boolean>) => ({ entry }),
        loadMoreBreakdownValues: true,
        setBreakdownValuesLoading: (loading: boolean) => ({ loading }),
        toggleLifecycle: (lifecycleName: string) => ({ lifecycleName }),
        setPersonsModalFilters: (searchTerm: string, people: TrendPeople) => ({ searchTerm, people }),
        saveFirstLoadedPeople: (
            people: PersonType[],
            count: number,
            action: ActionFilter | 'session',
            label: string,
            day: string | number,
            breakdown_value?: string,
            next?: string
        ) => ({
            people,
            count,
            action,
            label,
            day,
            breakdown_value,
            next,
        }),
        setFirstLoadedPeople: (firstLoadedPeople: TrendPeople | null) => ({ firstLoadedPeople }),
        setPeopleLoading: (loading: boolean) => ({ loading }),
    }),

    reducers: ({ props }) => ({
        filters: [
            (props.filters
                ? props.filters
                : (state: Record<string, any>) => cleanFilters(router.selectors.searchParams(state))) as Partial<
                FilterType
            >,
            {
                setFilters: (state, { filters, mergeFilters }) => {
                    const newState = state?.insight && TRENDS_BASED_INSIGHTS.includes(state.insight) ? state : {}
                    return cleanFilters({
                        ...(mergeFilters ? newState : {}),
                        ...filters,
                    })
                },
            },
        ],
        people: [
            null as TrendPeople | null,
            {
                setFilters: () => null,
                setPeople: (_, people) => people,
                setFirstLoadedPeople: (_, { firstLoadedPeople }) => firstLoadedPeople,
            },
        ],
        firstLoadedPeople: [
            null as TrendPeople | null,
            {
                saveFirstLoadedPeople: (_, people) => people,
            },
        ],
        loadingMorePeople: [
            false,
            {
                setLoadingMorePeople: (_, { status }) => status,
            },
        ],
        showingPeople: [
            false,
            {
                loadPeople: () => true,
                setShowingPeople: ({}, { isShowing }) => isShowing,
            },
        ],
        peopleLoading: [
            false,
            {
                setPeopleLoading: (_, { loading }) => loading,
            },
        ],
        indexedResults: [
            [] as IndexedTrendResult[],
            {
                setIndexedResults: ({}, { results }) => results,
            },
        ],
        toggledLifecycles: [
            ['new', 'resurrecting', 'returning', 'dormant'],
            {
                toggleLifecycle: (state, { lifecycleName }) => {
                    if (state.includes(lifecycleName)) {
                        return state.filter((lifecycles) => lifecycles !== lifecycleName)
                    }
                    state.push(lifecycleName)
                    return state
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
        filtersLoading: [
            () => [eventDefinitionsModel.selectors.loaded, propertyDefinitionsModel.selectors.loaded],
            (eventsLoaded, propertiesLoaded): boolean => !eventsLoaded || !propertiesLoaded,
        ],
        results: [(selectors) => [selectors._results], (response) => response.result],
        resultsLoading: [(selectors) => [selectors._resultsLoading], (_resultsLoading) => _resultsLoading],
        loadMoreBreakdownUrl: [(selectors) => [selectors._results], (response) => response.next],
        sessionsPageParams: [
            (selectors) => [selectors.filters, selectors.people],
            (filters, people) => {
                if (!people) {
                    return {}
                }

                const { action, day, breakdown_value } = people
                const properties = [...(filters.properties || []), ...(action !== 'session' ? action.properties : [])]
                if (filters.breakdown && filters.breakdown_type && breakdown_value) {
                    properties.push({
                        key: filters.breakdown,
                        value: breakdown_value,
                        type: filters.breakdown_type,
                        operator: null,
                    })
                }

                const eventProperties = properties.filter(({ type }) => type === 'event')
                const personProperties = properties.filter(({ type }) => type === 'person' || type === 'cohort')

                return {
                    date: day,
                    filters: [
                        {
                            type: action !== 'session' && action.type === 'actions' ? ACTION_TYPE : EVENT_TYPE,
                            key: 'id',
                            value: action !== 'session' && action['id'],
                            properties: eventProperties,
                            label: action !== 'session' && action.name,
                        },
                        ...personProperties,
                    ],
                }
            },
        ],
        numberOfSeries: [
            (selectors) => [selectors.filters],
            (filters): number => (filters.events?.length || 0) + (filters.actions?.length || 0),
        ],
    }),

    listeners: ({ actions, values, props }) => ({
        setDisplay: async ({ display }) => {
            actions.setFilters({ display })
        },
        toggleLifecycle: () => {
            const toggledResults = values.results
                .filter((result) => values.toggledLifecycles.includes(String(result.status)))
                .map((result, idx) => ({ ...result, id: idx }))
            actions.setIndexedResults(toggledResults)
        },
        refreshCohort: () => {
            cohortLogic({
                cohort: {
                    id: 'new',
                    groups: [],
                },
            }).actions.setCohort({
                id: 'new',
                groups: [],
            })
        },
        saveCohortWithFilters: ({ cohortName }) => {
            if (values.people) {
                const { label, action, day, breakdown_value } = values.people
                const filterParams = parsePeopleParams(
                    { label, action, date_from: day, date_to: day, breakdown_value },
                    values.filters
                )
                const cohortParams = {
                    is_static: true,
                    name: cohortName,
                }
                cohortLogic({
                    cohort: {
                        id: 'new',
                        groups: [],
                    },
                }).actions.saveCohort(cohortParams, filterParams)
            } else {
                errorToast(undefined, "We couldn't create your cohort:")
            }
        },
        loadPeople: async (
            { label, action, date_from, date_to, breakdown_value, saveOriginal, searchTerm, funnelStep },
            breakpoint
        ) => {
            actions.setPeopleLoading(true)
            let people = []
            const searchTermParam = searchTerm ? `&search=${encodeURIComponent(searchTerm)}` : ''
            if (values.filters.insight === ViewType.LIFECYCLE) {
                const filterParams = parsePeopleParams(
                    { label, action, target_date: date_from, lifecycle_type: breakdown_value },
                    values.filters
                )
                actions.setPeople([], 0, action, label, date_from, breakdown_value, '')
                people = await api.get(`api/person/lifecycle/?${filterParams}${searchTermParam}`)
            } else if (values.filters.insight === ViewType.STICKINESS) {
                const filterParams = parsePeopleParams(
                    { label, action, date_from, date_to, breakdown_value },
                    values.filters
                )
                actions.setPeople([], 0, action, label, date_from, breakdown_value, '')
                people = await api.get(`api/person/stickiness/?${filterParams}${searchTermParam}`)
            } else if (funnelStep) {
                const params = { ...funnelLogic().values.filters, funnel_step: funnelStep }
                const cleanedParams = cleanFunnelParams(params)
                const funnelParams = toParams(cleanedParams)
                people = await api.create(`api/person/funnel/?${funnelParams}${searchTermParam}`)
            } else {
                const filterParams = parsePeopleParams(
                    { label, action, date_from, date_to, breakdown_value },
                    values.filters
                )
                actions.setPeople([], 0, action, label, date_from, breakdown_value, '')
                people = await api.get(`api/action/people/?${filterParams}${searchTermParam}`)
            }
            breakpoint()
            actions.setPeople(
                people.results[0]?.people,
                people.results[0]?.count || 0,
                action,
                label,
                date_from,
                breakdown_value,
                people.next
            )
            actions.setPeopleLoading(false)
            if (saveOriginal) {
                actions.saveFirstLoadedPeople(
                    people.results[0]?.people,
                    people.results[0]?.count || 0,
                    action,
                    label,
                    date_from,
                    breakdown_value,
                    people.next
                )
            }
        },
        loadMorePeople: async ({}, breakpoint) => {
            if (values.people) {
                const { people: currPeople, count, action, label, day, breakdown_value, next } = values.people
                actions.setLoadingMorePeople(true)
                const people = await api.get(next)
                actions.setLoadingMorePeople(false)
                breakpoint()
                actions.setPeople(
                    [...currPeople, ...people.results[0]?.people],
                    count + people.results[0]?.count,
                    action,
                    label,
                    day,
                    breakdown_value,
                    people.next
                )
            }
        },
        setFilters: async () => {
            insightLogic.actions.setAllFilters(values.filters)
            actions.loadResults()
        },
        loadResultsSuccess: () => {
            if (!props.dashboardItemId) {
                insightHistoryLogic.actions.createInsight({
                    ...values.filters,
                    insight: values.filters.session ? ViewType.SESSIONS : values.filters.insight,
                })
            }

            let indexedResults
            if (values.filters.insight !== ViewType.LIFECYCLE) {
                indexedResults = values.results.map((element, index) => {
                    actions.setVisibilityById({ [`${index}`]: true })
                    return { ...element, id: index }
                })
            } else {
                indexedResults = values.results
                    .filter((result) => values.toggledLifecycles.includes(String(result.status)))
                    .map((result, idx) => {
                        actions.setVisibilityById({ [`${idx}`]: true })
                        return { ...result, id: idx }
                    })
            }
            actions.setIndexedResults(indexedResults)
        },
        [dashboardItemsModel.actionTypes.refreshAllDashboardItems]: (filters: Record<string, any>) => {
            if (props.dashboardItemId) {
                actions.setFilters(filters, true)
            }
        },
        loadMoreBreakdownValues: async () => {
            if (!values.loadMoreBreakdownUrl) {
                return
            }
            actions.setBreakdownValuesLoading(true)

            const response = await api.get(values.loadMoreBreakdownUrl)
            actions.loadResultsSuccess({
                result: [...values.results, ...(response.result ? response.result : [])],
                next: response.next,
            })
            actions.setBreakdownValuesLoading(false)
        },
        [eventDefinitionsModel.actionTypes.loadEventDefinitionsSuccess]: async () => {
            const newFilter = getDefaultFilters(values.filters, eventDefinitionsModel.values.eventNames)
            const mergedFilter: Partial<FilterType> = {
                ...values.filters,
                ...newFilter,
            }
            if (!objectsEqual(values.filters, mergedFilter)) {
                actions.setFilters(mergedFilter, true)
            }
        },
        setPersonsModalFilters: async ({ searchTerm, people }) => {
            const { label, action, day, breakdown_value } = people
            const date_from = day
            const date_to = day
            actions.loadPeople(action, label, date_from, date_to, breakdown_value, false, searchTerm)
        },
    }),

    events: ({ actions, props }) => ({
        afterMount: () => {
            if (props.dashboardItemId) {
                // loadResults gets called in urlToAction for non-dashboard insights
                actions.loadResults()
            }
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

                Object.assign(
                    cleanSearchParams,
                    getDefaultFilters(cleanSearchParams, eventDefinitionsModel.values.eventNames)
                )

                if (!objectsEqual(cleanSearchParams, values.filters)) {
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
