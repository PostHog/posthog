import { kea } from 'kea'

import api from 'lib/api'
import { fromParams, toParams } from 'lib/utils'
import { propertiesModel } from '~/models/propertiesModel'
import { actionsModel } from '~/models/actionsModel'

function cleanFilters(filters) {
    if (filters.breakdown && filters.display !== 'ActionsTable') {
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

function filtersFromParams() {
    let filters = fromParams()
    filters.actions = filters.actions && JSON.parse(filters.actions)
    filters.actions = Array.isArray(filters.actions) ? filters.actions : undefined
    filters.properties = filters.properties ? JSON.parse(filters.properties) : {}

    return cleanFilters(filters)
}

export const trendsLogic = kea({
    key: props => props.dashboardItemId || 'all_trends',

    connect: {
        values: [propertiesModel, ['properties'], actionsModel, ['actions']],
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
        setDefaultActionIfEmpty: true,

        showPeople: (action, day) => ({ action, day }),
        loadPeople: (action, day) => ({ action, day }),
        hidePeople: true,
        setPeople: (people, count) => ({ people, count }),
    }),

    reducers: ({ actions }) => ({
        filters: [
            {},
            {
                [actions.setFilters]: (state, { filters, mergeFilters }) =>
                    cleanFilters({
                        ...(mergeFilters ? state : {}),
                        ...filters,
                    }),
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
        [actions.loadActionsSuccess]: () => {
            if (!props.dashboardItemId) {
                actions.setDefaultActionIfEmpty()
            }
        },
        [actions.setDefaultActionIfEmpty]: () => {
            if (!values.filters.actions && values.actions.length > 0) {
                actions.setFilters({
                    actions: [
                        {
                            id: values.actions[values.actions.length - 1].id,
                        },
                    ],
                })
            }
        },
        [actions.setDisplay]: async ({ display }) => {
            actions.setFilters({ display })
        },
        [actions.showPeople]: async ({ action, day }) => {
            actions.setFilters({
                ...values.filters,
                people_day: day,
                people_action: action.id,
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
                actions: [{ id: action }],
            })

            if (`${day}`.match(/^\d{4}-\d{2}-\d{2}$/)) {
                params.date_from = day
                params.date_to = day
            } else {
                params.stickiness_days = day
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
                return `/trends?${toParams(values.filters)}`
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
            if (props.dashboardItemId) {
                // on dashboard
                actions.setFilters(props.filters, false)
            } else {
                actions.setFilters(filtersFromParams(), false)
                actions.setDefaultActionIfEmpty()
            }
        },
    }),
})
