import { kea } from 'kea'

import api from 'lib/api'
import { autocorrectInterval, errorToast, objectsEqual, toParams as toAPIParams, uuid } from 'lib/utils'
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
import { SESSIONS_WITH_RECORDINGS_FILTER } from 'scenes/sessions/filters/constants'
import {
    ActionFilter,
    ActionType,
    FilterType,
    PersonType,
    PropertyFilter,
    TrendResult,
    EntityTypes,
    PathType,
} from '~/types'
import { cohortLogic } from 'scenes/persons/cohortLogic'
import { trendsLogicType } from './trendsLogicType'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

interface TrendResponse {
    result: TrendResult[]
    next?: string
}

export interface IndexedTrendResult extends TrendResult {
    id: number
}

interface TrendPeople {
    people: PersonType[]
    breakdown_value?: string
    count: number
    day: string | number
    next?: string
    label: string
    action: ActionFilter
    loadingMore?: boolean
}

interface PeopleParamType {
    action: ActionFilter
    label: string
    date_to?: string | number
    date_from?: string | number
    breakdown_value?: string
    target_date?: number
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

function parsePeopleParams(peopleParams: PeopleParamType, filters: Partial<FilterType>): string {
    const { action, date_from, date_to, breakdown_value, ...restParams } = peopleParams
    const params = filterClientSideParams({
        ...filters,
        entity_id: action.id || filters?.events?.[0]?.id || filters?.actions?.[0]?.id,
        entity_type: action.type || filters?.events?.[0]?.type || filters?.actions?.[0]?.type,
        entity_math: action.math || undefined,
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
    if (action.properties) {
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
export const trendsLogic = kea<
    trendsLogicType<TrendResponse, IndexedTrendResult, TrendResult, FilterType, ActionType, TrendPeople, PropertyFilter>
>({
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

        loadPeople: (action, label, date_from, date_to, breakdown_value) => ({
            action,
            label,
            date_from,
            date_to,
            breakdown_value,
        }),
        saveCohortWithFilters: (cohortName: string) => ({ cohortName }),
        loadMorePeople: true,
        refreshCohort: true,
        setLoadingMorePeople: (status) => ({ status }),
        setShowingPeople: (isShowing) => ({ isShowing }),
        setPeople: (people, count, action, label, day, breakdown_value, next) => ({
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
                setVisibilityById: (state: Record<number, any>, { entry }: { entry: Record<number, any> }) => ({
                    ...state,
                    ...entry,
                }),
                toggleVisibility: (state: Record<number, any>, { index }: { index: number }) => ({
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
                const properties = [...(filters.properties || []), ...(action.properties || [])]
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
                            type: action.type === 'actions' ? ACTION_TYPE : EVENT_TYPE,
                            key: 'id',
                            value: action.id,
                            properties: eventProperties,
                            label: action.name,
                        },
                        ...personProperties,
                    ],
                }
            },
        ],
        peopleModalURL: [
            (selectors) => [selectors.sessionsPageParams],
            (params) => ({
                sessions: `/sessions?${toAPIParams(params)}`,
                recordings: `/sessions?${toAPIParams({
                    ...params,
                    filters: [...(params.filters || []), SESSIONS_WITH_RECORDINGS_FILTER],
                })}`,
            }),
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
        loadPeople: async ({ label, action, date_from, date_to, breakdown_value }, breakpoint) => {
            let people = []
            if (values.filters.insight === ViewType.LIFECYCLE) {
                const filterParams = parsePeopleParams(
                    { label, action, target_date: date_from, lifecycle_type: breakdown_value },
                    values.filters
                )
                actions.setPeople(null, null, action, label, date_from, breakdown_value, null)
                people = await api.get(`api/person/lifecycle/?${filterParams}`)
            } else if (values.filters.insight === ViewType.STICKINESS) {
                const filterParams = parsePeopleParams(
                    { label, action, date_from, date_to, breakdown_value },
                    values.filters
                )
                actions.setPeople(null, null, action, label, date_from, breakdown_value, null)
                people = await api.get(`api/person/stickiness/?${filterParams}`)
            } else {
                const filterParams = parsePeopleParams(
                    { label, action, date_from, date_to, breakdown_value },
                    values.filters
                )
                actions.setPeople(null, null, action, label, date_from, breakdown_value, null)
                people = await api.get(`api/action/people/?${filterParams}`)
            }
            breakpoint()
            actions.setPeople(
                people.results[0]?.people,
                people.results[0]?.count,
                action,
                label,
                date_from,
                breakdown_value,
                people.next
            )
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
            return ['/insights', values.filters, router.values.hashParams]
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
