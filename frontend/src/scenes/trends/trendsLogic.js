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
    if (filters.session && filters.session === 'dist') {
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
    if (filters.actions) {
        filters.actions = filters.actions.map((action, index) => ({ ...action, order: index }))
    }
    filters.events = filters.events && JSON.parse(filters.events)
    filters.events = Array.isArray(filters.events) ? filters.events : []
    filters.properties = filters.properties ? JSON.parse(filters.properties) : {}
    return cleanFilters(filters)
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
            loadResults: async () => {
                if (values.activeView === ViewType.SESSIONS) {
                    return await api.get('api/event/sessions/?' + toParams(filterClientSideParams(values.filters)))
                }
                return await api.get('api/action/trends/?' + toParams(filterClientSideParams(values.filters)))
            },
        },
    }),

    actions: () => ({
        setFilters: (filters, mergeFilters = true, fromUrl = false) => ({ filters, mergeFilters, fromUrl }),
        setDisplay: display => ({ display }),

        loadPeople: (action, day, breakdown_value) => ({ action, day, breakdown_value }),
        setShowingPeople: isShowing => ({ isShowing }),
        setPeople: (people, count, action, day, breakdown_value) => ({ people, count, action, day, breakdown_value }),
        setActiveView: type => ({ type }),
        setCachedUrl: (type, url) => ({ type, url }),
    }),

    reducers: ({ actions, props }) => ({
        filters: [
            props.dashboardItemId ? props.filters : filtersFromParams(),
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
        [actions.loadPeople]: async ({ action, day, breakdown_value }, breakpoint) => {
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
            if (breakdown_value) {
                params.properties = { ...params.properties, [params.breakdown]: breakdown_value }
            }

            const filterParams = toParams(params)
            actions.setPeople(null, null, action, day, breakdown_value)
            const people = await api.get(`api/action/people/?include_last_event=1&${filterParams}`)
            breakpoint()
            actions.setPeople(people[0]?.people, people[0]?.count, action, day, breakdown_value)
        },
    }),

    actionToUrl: ({ actions, values, props }) => ({
        [actions.setFilters]: ({ fromUrl }) => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }
            if (!fromUrl) {
                const oldFilters = filtersFromParams()

                if (toParams(oldFilters) !== toParams(values.filters)) {
                    return `/trends?${toParams(values.filters)}`
                }
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
            return type === ViewType.SESSIONS ? `/trends?${toParams({ session: 'avg' })}` : `/trends`
        },
    }),

    urlToAction: ({ actions, values, props }) => ({
        '/trends': () => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }

            const newFilters = filtersFromParams()
            if (toParams(newFilters) !== toParams(values.filters)) {
                actions.setFilters(newFilters, false, true)
            }
        },
    }),
})
