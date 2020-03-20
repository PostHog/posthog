import { kea } from 'kea'

import api from 'lib/api'
import { fromParams, toParams } from 'lib/utils'

function filtersFromParams() {
    let filters = fromParams()
    filters.actions = filters.actions && JSON.parse(filters.actions)
    filters.actions = Array.isArray(filters.actions) ? filters.actions : undefined
    if (filters.breakdown) filters.display = 'ActionsTable'
    filters.properties = filters.properties ? JSON.parse(filters.properties) : {}

    return filters
}

export const trendsLogic = kea({
    actions: () => ({
        fetchActions: true,
        setActions: actions => ({ actions }),

        fetchProperties: true,
        setProperties: properties => ({ properties }),

        setFilters: (filters, mergeFilters = true) => ({ filters, mergeFilters }),
        setDisplay: display => ({ display }),

        loadData: true,
        setData: data => ({ data }),

        showPeople: (action, day) => ({ action, day }),
        loadPeople: (action, day) => ({ action, day }),
        hidePeople: true,
        setPeople: (people, count) => ({ people, count }),
    }),

    reducers: ({ actions }) => ({
        actions: [
            [],
            {
                [actions.setActions]: (_, { actions }) => actions,
            },
        ],
        properties: [
            [],
            {
                [actions.setProperties]: (_, { properties }) => properties,
            },
        ],
        data: [
            [],
            {
                [actions.setData]: (_, { data }) => data,
            },
        ],
        filters: [
            {},
            {
                [actions.setFilters]: (state, { filters, mergeFilters }) => {
                    const newFilters = {
                        ...(mergeFilters ? state : {}),
                        ...filters,
                    }

                    if (newFilters.breakdown) {
                        newFilters.display = 'ActionsTable'
                    }

                    return newFilters
                },
            },
        ],
        isLoading: [
            true,
            {
                [actions.loadData]: () => true,
                [actions.setData]: () => false,
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

    listeners: ({ actions, values }) => ({
        [actions.fetchActions]: async () => {
            const allActions = (await api.get('api/action')).results

            // autoselect last action if none selected
            if (!values.filters.actions && allActions.length > 0) {
                actions.setFilters({
                    actions: [
                        {
                            id: allActions[allActions.length - 1].id,
                        },
                    ],
                })
            }

            actions.setActions(allActions)
        },
        [actions.fetchProperties]: async () => {
            const properties = await api.get('api/event/properties')
            actions.setProperties(
                properties.map(property => ({
                    label: property.name,
                    value: property.name,
                }))
            )
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
        [actions.loadData]: async (_, breakpoint) => {
            const data = await api.get('api/action/trends/?' + toParams(values.filters))
            breakpoint()
            actions.setData(data)
        },
        [actions.loadPeople]: async ({ day, action }, breakpoint) => {
            const filterParams = toParams({
                ...values.filters,
                actions: [{ id: action }],
                date_from: day,
                date_to: day,
            })
            const people = await api.get(`api/action/people/?${filterParams}`)

            if (day === values.filters.people_day && action === values.filters.people_action) {
                actions.setPeople(people[0]?.people, people[0]?.count)
            }
        },
    }),

    actionToUrl: ({ actions, values }) => ({
        [actions.setFilters]: () => `/trends?${toParams(values.filters)}`,
    }),

    urlToAction: ({ actions, values }) => ({
        '/trends': () => {
            const newFilters = filtersFromParams()

            if (toParams(newFilters) !== toParams(values.filters)) {
                actions.setFilters(newFilters, false)
            }
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.fetchActions()
            actions.fetchProperties()
            actions.setFilters(filtersFromParams(), false)
        },
    }),
})
