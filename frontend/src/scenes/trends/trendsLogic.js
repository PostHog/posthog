import { kea } from 'kea'

import api from 'lib/api'
import { objectsEqual, toParams as toAPIParams } from 'lib/utils'
import { actionsModel } from '~/models/actionsModel'
import { userLogic } from 'scenes/userLogic'
import { router } from 'kea-router'
import { STICKINESS, ACTIONS_LINE_GRAPH_CUMULATIVE } from 'lib/constants'

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

export const ViewType = {
    FILTERS: 'FILTERS',
    SESSIONS: 'SESSIONS',
}

function cleanFilters(filters) {
    return {
        ...filters,
        interval: autocorrectInterval(filters),
        display: filters.session && filters.session === 'dist' ? 'ActionsTable' : filters.display,
        actions: Array.isArray(filters.actions) ? filters.actions : undefined,
        events: Array.isArray(filters.events) ? filters.events : undefined,
        properties: filters.properties || [],
    }
}

function filterClientSideParams(filters) {
    const {
        people_day: _skip_this_one,
        people_action: _skip_this_too,
        stickiness_days: __and_this,
        ...newFilters
    } = filters

    return newFilters
}

function autocorrectInterval({ date_from, interval }) {
    if (!interval) return 'day' // undefined/uninitialized

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

// props:
// - dashboardItemId
// - filters
export const trendsLogic = kea({
    key: props => props.dashboardItemId || 'all_trends',

    connect: {
        values: [userLogic, ['eventNames'], actionsModel, ['actions']],
    },

    loaders: ({ values }) => ({
        results: {
            loadResults: async (_, breakpoint) => {
                let response
                if (values.activeView === ViewType.SESSIONS) {
                    response = await api.get(
                        'api/event/sessions/?' + toAPIParams(filterClientSideParams(values.filters))
                    )
                } else {
                    response = await api.get(
                        'api/action/trends/?' + toAPIParams(filterClientSideParams(values.filters))
                    )
                }
                breakpoint()
                return response
            },
        },
    }),

    actions: () => ({
        setFilters: (filters, mergeFilters = true, fromUrl = false) => ({ filters, mergeFilters, fromUrl }),
        setDisplay: display => ({ display }),

        loadPeople: (action, label, day, breakdown_value) => ({ action, label, day, breakdown_value }),
        setShowingPeople: isShowing => ({ isShowing }),
        setPeople: (people, count, action, label, day, breakdown_value) => ({
            people,
            count,
            action,
            label,
            day,
            breakdown_value,
        }),
        setActiveView: type => ({ type }),
        setCachedUrl: (type, url) => ({ type, url }),
    }),

    reducers: ({ actions, props }) => ({
        filters: [
            props.dashboardItemId ? props.filters : state => cleanFilters(router.selectors.searchParams(state)),
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
            },
        ],
        cachedUrls: [
            {},
            {
                [actions.setCachedUrl]: (state, { type, url }) => ({ ...state, [type]: url }),
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
        activeView: [() => [selectors.filters], filters => (filters.session ? ViewType.SESSIONS : ViewType.FILTERS)],
        peopleAction: [
            () => [selectors.filters, selectors.actions],
            (filters, actions) =>
                filters.people_action ? actions.find(a => a.id === parseInt(filters.people_action)) : null,
        ],
        peopleDay: [() => [selectors.filters], filters => filters.people_day],
    }),

    listeners: ({ actions, values }) => ({
        [actions.setDisplay]: async ({ display }) => {
            actions.setFilters({ display })
        },
        [actions.loadPeople]: async ({ label, action, day, breakdown_value }, breakpoint) => {
            const params = filterClientSideParams({
                ...values.filters,
                entityId: action.id,
                type: action.type,
                breakdown_value,
            })

            if (values.filters.shown_as === STICKINESS) {
                params.stickiness_days = day
            } else if (params.display === ACTIONS_LINE_GRAPH_CUMULATIVE) {
                params.date_to = day
            } else {
                params.date_from = day
                params.date_to = day
            }
            // If breakdown type is cohort, we use breakdown_value
            // If breakdown type is event, we just set another filter
            if (breakdown_value && values.filters.breakdown_type != 'cohort') {
                params.properties = [
                    ...params.properties,
                    { key: params.breakdown, value: breakdown_value, type: 'event' },
                ]
            }

            const filterParams = toAPIParams(params)
            actions.setPeople(null, null, action, label, day, breakdown_value)
            const people = await api.get(`api/action/people/?include_last_event=1&${filterParams}`)
            breakpoint()
            actions.setPeople(people[0]?.people, people[0]?.count, action, label, day, breakdown_value)
        },
    }),

    actionToUrl: ({ actions, values, props }) => ({
        [actions.setFilters]: ({ fromUrl }) => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }
            if (!fromUrl) {
                return ['/trends', values.filters]
            }
        },
        [actions.setActiveView]: ({ type }) => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }
            actions.setCachedUrl(values.activeView, window.location.pathname + window.location.search)
            const cachedUrl = values.cachedUrls[type]
            if (cachedUrl) {
                return cachedUrl
            }
            return ['/trends', type === ViewType.SESSIONS ? { session: 'avg' } : {}]
        },
    }),

    urlToAction: ({ actions, values, props }) => ({
        '/trends': (_, searchParams) => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }

            const cleanSearchParams = cleanFilters(searchParams)

            const keys = Object.keys(searchParams)
            // opening /trends without any params, just open $pageview, $screen or the first random event
            if (
                (keys.length === 0 || (keys.length === 1 && keys[0] === 'properties')) &&
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

            if (!objectsEqual(cleanSearchParams, values.filters)) {
                actions.setFilters(cleanSearchParams, false, true)
            }
        },
    }),
})
