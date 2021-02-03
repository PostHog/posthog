import { kea } from 'kea'

import api from 'lib/api'
import { objectsEqual, toParams as toAPIParams } from 'lib/utils'
import { actionsModel } from '~/models/actionsModel'
import { userLogic } from 'scenes/userLogic'
import { router } from 'kea-router'
import {
    ACTIONS_LINE_GRAPH_CUMULATIVE,
    ACTIONS_LINE_GRAPH_LINEAR,
    ACTIONS_TABLE,
    PAGEVIEW,
    SCREEN,
    EVENT_TYPE,
    ACTION_TYPE,
    ShownAsValue,
} from 'lib/constants'
import { ViewType, insightLogic } from './insightLogic'
import { insightHistoryLogic } from './InsightHistoryPanel/insightHistoryLogic'
import { SESSIONS_WITH_RECORDINGS_FILTER } from 'scenes/sessions/filters/constants'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ActionType, EntityType, FilterType, PersonType, PropertyFilter } from '~/types'
import { trendsLogicType } from './trendsLogicType'
import { ToastId } from 'react-toastify'

interface ActionFilter {
    id: number | string
    math?: string
    math_property?: string
    name: string
    order: number
    properties: PropertyFilter[]
    type: EntityType
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
    day?: string | number
    breakdown_value?: string
    target_date?: number
    lifecycle_type?: string
}

export const EntityTypes: Record<string, string> = {
    ACTIONS: 'actions',
    EVENTS: 'events',
    NEW_ENTITY: 'new_entity',
}

export const disableMinuteFor: Record<string, boolean> = {
    dStart: false,
    '-1d': false,
    '-7d': true,
    '-14d': true,
    '-30d': true,
    '-90d': true,
    mStart: true,
    '-1mStart': true,
    yStart: true,
    all: true,
}

export const disableHourFor: Record<string, boolean> = {
    dStart: false,
    '-1d': false,
    '-7d': false,
    '-14d': false,
    '-30d': false,
    '-90d': true,
    mStart: false,
    '-1mStart': false,
    yStart: true,
    all: true,
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

function autocorrectInterval({ date_from, interval }: Partial<FilterType>): string {
    if (!interval) {
        return 'day'
    } // undefined/uninitialized

    const minute_disabled = date_from && disableMinuteFor[date_from] && interval === 'minute'
    const hour_disabled = date_from && disableHourFor[date_from] && interval === 'hour'

    if (minute_disabled) {
        return 'hour'
    } else if (hour_disabled) {
        return 'day'
    } else {
        return interval
    }
}

function parsePeopleParams(peopleParams: PeopleParamType, filters: Partial<FilterType>): string {
    const { action, day, breakdown_value, ...restParams } = peopleParams
    const params = filterClientSideParams({
        ...filters,
        entityId: action.id,
        type: action.type,
        breakdown_value,
    })

    // casting here is not the best
    if (filters.shown_as === ShownAsValue.STICKINESS) {
        params.stickiness_days = day as number
    } else if (params.display === ACTIONS_LINE_GRAPH_CUMULATIVE) {
        params.date_to = day as string
    } else if (filters.shown_as === ShownAsValue.LIFECYCLE) {
        params.date_from = filters.date_from
        params.date_to = filters.date_to
    } else {
        params.date_from = day as string
        params.date_to = day as string
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

// props:
// - dashboardItemId
// - filters
export const trendsLogic = kea<trendsLogicType<FilterType, ActionType, TrendPeople, PropertyFilter, ToastId>>({
    key: (props) => {
        return props.dashboardItemId || 'all_trends'
    },

    connect: {
        values: [userLogic, ['eventNames'], actionsModel, ['actions'], insightLogic, ['isFirstLoad']],
        actions: [insightHistoryLogic, ['createInsight']],
    },

    loaders: ({ values, props }) => ({
        results: {
            __default: [],
            loadResults: async (refresh = false, breakpoint) => {
                if (props.cachedResults && !refresh) {
                    return props.cachedResults
                }
                insightLogic.actions.startQuery()
                let response
                try {
                    if (values.filters?.insight === ViewType.SESSIONS || values.filters?.session) {
                        response = await api.get(
                            'api/insight/session/?' +
                                (refresh ? 'refresh=true&' : '') +
                                toAPIParams(filterClientSideParams(values.filters))
                        )
                        response = response.result
                    } else {
                        response = await api.get(
                            'api/insight/trend/?' +
                                (refresh ? 'refresh=true&' : '') +
                                toAPIParams(filterClientSideParams(values.filters))
                        )
                    }
                } catch (e) {
                    insightLogic.actions.endQuery(values.filters.insight || ViewType.TRENDS, e)
                    return []
                }
                insightLogic.actions.endQuery(values.filters.insight || ViewType.TRENDS)
                breakpoint()
                return response
            },
        },
    }),

    actions: () => ({
        setFilters: (filters, mergeFilters = true) => ({ filters, mergeFilters }),
        setDisplay: (display) => ({ display }),

        loadPeople: (action, label, day, breakdown_value) => ({ action, label, day, breakdown_value }),
        loadMorePeople: true,
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
                    return cleanFilters({
                        ...(mergeFilters ? state : {}),
                        ...filters,
                    })
                },
            },
        ],
        people: [
            {} as TrendPeople | null,
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
    }),

    selectors: ({ selectors }) => ({
        sessionsPageParams: [
            () => [selectors.filters, selectors.people],
            (filters, people) => {
                if (!people) {
                    return {}
                }

                const { action, day, breakdown_value } = people
                const properties = filters.properties || []
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
            () => [selectors.sessionsPageParams],
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
        loadPeople: async ({ label, action, day, breakdown_value }, breakpoint) => {
            let people = []
            if (values.filters.shown_as === ShownAsValue.LIFECYCLE) {
                const filterParams = parsePeopleParams(
                    { label, action, target_date: day, lifecycle_type: breakdown_value },
                    values.filters
                )
                actions.setPeople(null, null, action, label, day, breakdown_value, null)
                people = await api.get(`api/person/lifecycle/?${filterParams}`)
            } else if (values.filters.shown_as === ShownAsValue.STICKINESS) {
                const filterParams = parsePeopleParams({ label, action, day, breakdown_value }, values.filters)
                actions.setPeople(null, null, action, label, day, breakdown_value, null)
                people = await api.get(`api/person/stickiness/?${filterParams}`)
            } else {
                const filterParams = parsePeopleParams({ label, action, day, breakdown_value }, values.filters)
                actions.setPeople(null, null, action, label, day, breakdown_value, null)
                people = await api.get(`api/action/people/?${filterParams}`)
            }
            breakpoint()
            actions.setPeople(
                people.results[0]?.people,
                people.results[0]?.count,
                action,
                label,
                day,
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
                actions.createInsight({
                    ...values.filters,
                    insight: values.filters.session ? ViewType.SESSIONS : ViewType.TRENDS,
                })
            }
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadResults()
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
            if (
                !searchParams.insight ||
                searchParams.insight === ViewType.TRENDS ||
                searchParams.insight === ViewType.SESSIONS ||
                searchParams.insight === ViewType.STICKINESS ||
                searchParams.insight === ViewType.LIFECYCLE
            ) {
                if (props.dashboardItemId) {
                    actions.loadResults()
                    return // don't use the URL if on the dashboard
                }

                const cleanSearchParams = cleanFilters(searchParams)

                const keys = Object.keys(searchParams)

                // opening /trends without any params, just open $pageview, $screen or the first random event
                if (
                    (keys.length === 0 || (!searchParams.actions && !searchParams.events)) &&
                    values.eventNames &&
                    values.eventNames[0]
                ) {
                    const event = values.eventNames.includes(PAGEVIEW)
                        ? PAGEVIEW
                        : values.eventNames.includes(SCREEN)
                        ? SCREEN
                        : values.eventNames[0]

                    cleanSearchParams[EntityTypes.EVENTS] = [
                        {
                            id: event,
                            name: event,
                            type: EntityTypes.EVENTS,
                            order: 0,
                        },
                    ]
                }

                if (searchParams.insight === ViewType.STICKINESS) {
                    cleanSearchParams['shown_as'] = ShownAsValue.STICKINESS
                }
                if (searchParams.insight === ViewType.LIFECYCLE) {
                    cleanSearchParams['shown_as'] = ShownAsValue.LIFECYCLE
                }

                if (searchParams.insight === ViewType.SESSIONS && !searchParams.session) {
                    cleanSearchParams['session'] = 'avg'
                }
                if (!objectsEqual(cleanSearchParams, values.filters)) {
                    actions.setFilters(cleanSearchParams, false)
                } else {
                    /* Edge case when opening a trends graph from a dashboard or sometimes when trends are loaded
                    with filters already set, `setAllFilters` action is not triggered, and therefore usage is not reported */
                    eventUsageLogic.actions.reportInsightViewed(values.filters, values.isFirstLoad)
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
    if (params.shown_as === ShownAsValue.LIFECYCLE) {
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
