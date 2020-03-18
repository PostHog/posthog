import { kea } from 'kea'

import api from 'lib/api'
import { fromParams, toParams } from 'lib/utils'

function filtersFromParams() {
    let filters = fromParams()
    filters.actions = filters.actions && JSON.parse(filters.actions)
    filters.actions = Array.isArray(filters.actions)
        ? filters.actions
        : undefined
    if (filters.breakdown) filters.display = 'ActionsTable'
    filters.properties = filters.properties
        ? JSON.parse(filters.properties)
        : {}

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
                [actions.setDisplay]: (state, { display }) => ({
                    ...state,
                    display,
                }),
            },
        ],
        isLoading: [
            true,
            {
                [actions.setFilters]: () => true,
                [actions.setData]: () => false,
            },
        ],
    }),

    listeners: ({ actions, values }) => ({
        [actions.fetchActions]: async () => {
            try {
                const allActions = (await api.get('api/action')).results

                // autoselect last action if none selected
                if (!values.filters.actions && allActions.length > 0) {
                    allActions.setFilters({
                        actions: [
                            {
                                id: allActions[allActions.length - 1].id,
                            },
                        ],
                    })
                }

                actions.setActions(allActions)
            } catch (error) {
                // TODO: show error for loading actions
            }
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
