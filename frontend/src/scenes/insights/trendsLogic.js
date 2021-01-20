import { kea } from 'kea'

import api from 'lib/api'
import { objectsEqual, toParams as toAPIParams } from 'lib/utils'
import { actionsModel } from '~/models/actionsModel'
import { userLogic } from 'scenes/userLogic'
import { router } from 'kea-router'
import {
    STICKINESS,
    ACTIONS_LINE_GRAPH_CUMULATIVE,
    ACTIONS_LINE_GRAPH_LINEAR,
    ACTIONS_TABLE,
    LIFECYCLE,
} from 'lib/constants'
import { ViewType, insightLogic } from './insightLogic'
import { insightHistoryLogic } from './InsightHistoryPanel/insightHistoryLogic'
import { SESSIONS_WITH_RECORDINGS_FILTER } from 'scenes/sessions/filters/constants'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export const EntityTypes = {
    ACTIONS: 'actions',
    EVENTS: 'events',
    NEW_ENTITY: 'new_entity',
}

export const disableMinuteFor = {
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

export const disableHourFor = {
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

function cleanFilters(filters) {
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

function filterClientSideParams(filters) {
    const {
        people_day: _skip_this_one, // eslint-disable-line
        people_action: _skip_this_too, // eslint-disable-line
        stickiness_days: __and_this, // eslint-disable-line
        ...newFilters
    } = filters

    return newFilters
}

function autocorrectInterval({ date_from, interval }) {
    if (!interval) {
        return 'day'
    } // undefined/uninitialized

    const minute_disabled = disableMinuteFor[date_from] && interval === 'minute'
    const hour_disabled = disableHourFor[date_from] && interval === 'hour'

    if (minute_disabled) {
        return 'hour'
    } else if (hour_disabled) {
        return 'day'
    } else {
        return interval
    }
}

function parsePeopleParams(peopleParams, filters) {
    const { action, day, breakdown_value, ...restParams } = peopleParams
    const params = filterClientSideParams({
        ...filters,
        entityId: action.id,
        type: action.type,
        breakdown_value,
    })

    if (filters.shown_as === STICKINESS) {
        params.stickiness_days = day
    } else if (params.display === ACTIONS_LINE_GRAPH_CUMULATIVE) {
        params.date_to = day
    } else if (filters.shown_as === LIFECYCLE) {
        params.date_from = filters.date_from
        params.date_to = filters.date_to
    } else {
        params.date_from = day
        params.date_to = day
    }
    // If breakdown type is cohort, we use breakdown_value
    // If breakdown type is event, we just set another filter
    if (breakdown_value && filters.breakdown_type != 'cohort' && filters.breakdown_type != 'person') {
        params.properties = [...params.properties, { key: params.breakdown, value: breakdown_value, type: 'event' }]
    }
    if (action.properties) {
        params.properties = [...params.properties, ...action.properties]
    }

    return toAPIParams({ ...params, ...restParams })
}

// props:
// - dashboardItemId
// - filters
export const trendsLogic = kea({
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
                    insightLogic.actions.endQuery(values.filters.insight, e)
                    return []
                }
                insightLogic.actions.endQuery(values.filters.insight)
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

    reducers: ({ actions, props }) => ({
        filters: [
            props.filters ? props.filters : (state) => cleanFilters(router.selectors.searchParams(state)),
            {
                [actions.setFilters]: (state, { filters, mergeFilters }) => {
                    return cleanFilters({
                        ...(mergeFilters ? state : {}),
                        ...filters,
                    })
                },
            },
        ],
        people: [
            null,
            {
                [actions.setFilters]: () => null,
                [actions.setPeople]: (_, people) => people,
                [actions.setLoadingMorePeople]: (state, { status }) => ({ ...state, loadingMore: status }),
            },
        ],
        showingPeople: [
            false,
            {
                [actions.loadPeople]: () => true,
                [actions.setShowingPeople]: (_, { isShowing }) => isShowing,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        peopleAction: [
            () => [selectors.filters, selectors.actions],
            (filters, actions) =>
                filters.people_action ? actions.find((a) => a.id === parseInt(filters.people_action)) : null,
        ],
        peopleDay: [() => [selectors.filters], (filters) => filters.people_day],

        sessionsPageParams: [
            () => [selectors.filters, selectors.people],
            (filters, people) => {
                if (!people) {
                    return {}
                }

                const { action, day, breakdown_value } = people
                const properties = [...filters.properties]
                if (filters.breakdown) {
                    properties.push({ key: filters.breakdown, value: breakdown_value, type: filters.breakdown_type })
                }

                const eventProperties = properties.filter(({ type }) => type === 'event')
                const personProperties = properties.filter(({ type }) => type === 'person' || type === 'cohort')

                return {
                    date: day,
                    filters: [
                        {
                            type: action.type === 'actions' ? 'action_type' : 'event_type',
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
        [actions.setDisplay]: async ({ display }) => {
            actions.setFilters({ display })
        },
        [actions.loadPeople]: async ({ label, action, day, breakdown_value }, breakpoint) => {
            let people = []
            if (values.filters.shown_as === LIFECYCLE) {
                const filterParams = parsePeopleParams(
                    { label, action, target_date: day, lifecycle_type: breakdown_value },
                    values.filters
                )
                actions.setPeople(null, null, action, label, day, breakdown_value, null)
                people = await api.get(`api/person/lifecycle/?${filterParams}`)
            } else if (values.filters.shown_as === STICKINESS) {
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
        [actions.loadMorePeople]: async (_, breakpoint) => {
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

    actionToUrl: ({ actions, values, props }) => ({
        [actions.setFilters]: () => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }
            return ['/insights', values.filters, router.values.hashParams]
        },
    }),

    urlToAction: ({ actions, values, props }) => ({
        '/insights': (_, searchParams) => {
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
                    const event = values.eventNames.includes('$pageview')
                        ? '$pageview'
                        : values.eventNames.includes('$screen')
                        ? '$screen'
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
                    cleanSearchParams['shown_as'] = 'Stickiness'
                }
                if (searchParams.insight === ViewType.LIFECYCLE) {
                    cleanSearchParams['shown_as'] = 'Lifecycle'
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

const handleLifecycleDefault = (params, callback) => {
    if (params.shown_as === LIFECYCLE) {
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
