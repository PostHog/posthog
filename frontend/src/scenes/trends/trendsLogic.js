import { kea } from 'kea'

import api from 'lib/api'
import { fromParams, toParams } from 'lib/utils'
import { actionsModel } from '~/models/actionsModel'
import { userLogic } from 'scenes/userLogic'

export const EntityTypes = {
    ACTIONS: 'actions',
    EVENTS: 'events',
    NEW: 'new',
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
    if ((filters.breakdown && filters.display !== 'ActionsTable') || filters.session) {
        return {
            ...filters,
            display: 'ActionsTable',
        }
    }
    return filters
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

function filtersFromParams() {
    let filters = fromParams()
    filters.interval = autocorrectInterval(filters)
    filters.actions = filters.actions && JSON.parse(filters.actions)
    filters.actions = Array.isArray(filters.actions) ? filters.actions : undefined
    filters.events = filters.events && JSON.parse(filters.events)
    filters.events = Array.isArray(filters.events) ? filters.events : []
    filters.properties = filters.properties ? JSON.parse(filters.properties) : {}
    return cleanFilters(filters)
}

export const trendsLogic = kea({
    key: props => props.dashboardItemId || 'all_trends',

    connect: {
        values: [userLogic, ['eventNames'], actionsModel, ['actions']],
        actions: [actionsModel, ['loadActionsSuccess']],
    },

    loaders: ({ values }) => ({
        results: {
            loadResults: async () => {
                return await api.get('api/action/trends/?' + toParams(filterClientSideParams(values.filters)))
            },
        },
    }),

    actions: () => ({
        setFilters: (filters, mergeFilters = true) => ({ filters, mergeFilters }),
        setDisplay: display => ({ display }),

        showPeople: (action, day) => ({ action, day }),
        loadPeople: (action, day) => ({ action, day }),
        hidePeople: true,
        setPeople: (people, count) => ({ people, count }),
        setActiveView: type => ({ type }),
        initialView: type => ({ type }),
        setCachedUrl: url => ({ url }),
        clearCachedUrl: true,
    }),

    reducers: ({ actions }) => ({
        filters: [
            {},
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
                [actions.setPeople]: (_, { people }) => people,
            },
        ],
        peopleCount: [
            null,
            {
                [actions.setFilters]: () => null,
                [actions.setPeople]: (_, { count }) => count,
            },
        ],
        activeView: [
            ViewType.FILTERS,
            {
                [actions.setActiveView]: (_, { type }) => type,
                [actions.initialView]: (_, { type }) => type,
            },
        ],
        cachedUrl: [
            null,
            {
                [actions.setCachedUrl]: (_, { url }) => url,
                [actions.clearCachedUrl]: _ => null,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        showingPeople: [() => [selectors.filters], filters => !!(filters.people_action && filters.people_day)],
        peopleAction: [
            () => [selectors.filters, selectors.actions],
            (filters, actions) =>
                filters.people_action ? actions.find(a => a.id === parseInt(filters.people_action)) : null,
        ],
        peopleDay: [() => [selectors.filters], (filters, actions) => filters.people_day],
    }),

    listeners: ({ actions, values, props }) => ({
        [actions.setDisplay]: async ({ display }) => {
            actions.setFilters({ display })
        },
        [actions.showPeople]: async ({ action, day }) => {
            actions.setFilters({
                ...values.filters,
                people_day: day,
                people_action: action,
            })
        },
        [actions.hidePeople]: async () => {
            actions.setFilters({
                ...values.filters,
                people_day: '',
                people_action: '',
            })
        },
        [actions.setFilters]: async ({ filters }) => {
            if (filters.people_day && filters.people_action) {
                actions.loadPeople(filters.people_action, filters.people_day)
            }
        },
        [actions.loadPeople]: async ({ day, action }) => {
            const params = filterClientSideParams({
                ...values.filters,
                entityId: action.id,
                type: action.type,
            })

            if (values.filters.shown_as === 'Stickiness') {
                params.stickiness_days = day
            } else {
                params.date_from = day
                params.date_to = day
            }

            const filterParams = toParams(params)
            const people = await api.get(`api/action/people/?include_last_event=1&${filterParams}`)
            if (day === values.filters.people_day && action === values.filters.people_action) {
                actions.setPeople(people[0]?.people, people[0]?.count)
            }
        },
    }),

    actionToUrl: ({ actions, values, props }) => ({
        [actions.setFilters]: () => {
            if (!props.dashboardItemId) {
                const url = `/trends?${toParams(values.filters)}`
                // temporary check to disable double back button
                // as react-router and kea-router don't sync super well
                if (window.location.pathname + window.location.search !== url) {
                    return url
                }
            }
        },
        [actions.setActiveView]: ({ type }) => {
            let cachedUrl = values.cachedUrl
            actions.setCachedUrl(window.location.pathname + window.location.search)
            if (cachedUrl) {
                return cachedUrl
            } else {
                return type == ViewType.SESSIONS
                    ? `/trends?${toParams({ session: 'avg' })}`
                    : `/trends?${toParams({ ...values.filters, display: 'ActionsLineGraph', session: null })}`
            }
        },
    }),

    urlToAction: ({ actions, values, props }) => ({
        '/trends': () => {
            if (!props.dashboardItemId) {
                const newFilters = filtersFromParams()
                if (toParams(newFilters) !== toParams(values.filters)) {
                    actions.setFilters(newFilters, false)
                }
            }
        },
    }),

    events: ({ actions, props }) => ({
        afterMount: () => {
            let filters = filtersFromParams()
            if (filters.session) {
                actions.initialView(ViewType.SESSIONS)
                actions.setFilters(filters, false)
            } else if (props.dashboardItemId) {
                // on dashboard
                actions.setFilters(props.filters, false)
            } else {
                actions.setFilters(filters, false)
            }
        },
    }),
})
