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

        setFilters: filters => ({ filters }),
        setDisplay: display => ({ display }),
        setData: data => ({ data }),

        showPeople: (action, day) => ({ action, day }),
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
            filtersFromParams,
            {
                [actions.setFilters]: (state, { filters }) => {
                    const newFilters = {
                        ...state,
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
                [actions.setFilters]: () => true,
                [actions.setData]: () => false,
            },
        ],
        showingPeople: [
            false,
            {
                [actions.showPeople]: () => true,
                [actions.hidePeople]: () => false,
            },
        ],
        people: [
            null,
            {
                [actions.showPeople]: () => null,
                [actions.setPeople]: (_, { people }) => people,
                [actions.hidePeople]: () => null,
            },
        ],
        peopleMeta: [
            {},
            {
                [actions.showPeople]: (_, { action, day }) => ({ action, day }),
                [actions.setPeople]: (state, { count }) => ({
                    ...state,
                    count,
                }),
                [actions.hidePeople]: () => ({}),
            },
        ],
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
            try {
                const properties = await api.get('api/event/properties')
                actions.setProperties(
                    properties.map(property => ({
                        label: property.name,
                        value: property.name,
                    }))
                )
            } catch (error) {
                // TODO: show error for loading properties
            }
        },
        [actions.setDisplay]: async ({ display }) => {
            actions.setFilters({ display })
        },
        [actions.showPeople]: async ({ action, day }, breakpoint) => {
            const filterParams = toParams({
                actions: [{ id: action.id }],
                ...values.filters,
            })
            const url = `api/action/people/?${filterParams}&date_from=${day}&date_to=${day}`
            const people = await api.get(url)
            breakpoint()

            actions.setPeople(people[0]?.people, people[0]?.count)
        },
    }),

    actionToUrl: ({ actions, values }) => ({
        [actions.setFilters]: () => `/trends?${toParams(values.filters)}`,
    }),

    urlToAction: ({ actions, values }) => ({
        '/trends': () => actions.setFilters(filtersFromParams()),
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.fetchActions()
            actions.fetchProperties()
        },
    }),
})
