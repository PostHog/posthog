import { kea } from 'kea'
import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'
import { objectsEqual } from 'lib/utils'
import { router } from 'kea-router'

export function parseProperties(input) {
    if (Array.isArray(input) || !input) {
        return input
    }
    // Old style dict properties
    return Object.entries(input).map(([key, value]) => {
        key = key.split('__')
        return {
            key: key[0],
            value,
            operator: key[1],
            type: 'event',
        }
    })
}

export const propertyFilterLogic = kea({
    key: (props) => props.pageKey,

    actions: () => ({
        loadEventProperties: true,
        setProperties: (properties) => ({ properties }),
        update: (filters) => ({ filters }),
        setFilter: (index, key, value, operator, type) => ({ index, key, value, operator, type }),
        setFilters: (filters) => ({ filters }),
        newFilter: true,
        remove: (index) => ({ index }),
    }),

    loaders: () => ({
        personProperties: {
            loadPersonProperties: async () => {
                return (await api.get('api/person/properties')).map((property) => ({
                    label: property.name,
                    value: property.name,
                }))
            },
        },
    }),

    reducers: ({ actions, props }) => ({
        eventProperties: [
            [],
            {
                [actions.setProperties]: (_, { properties }) => properties,
            },
        ],
        filters: [
            props.propertyFilters ? parseProperties(props.propertyFilters) : [],
            {
                [actions.setFilter]: (state, { index, key, value, operator, type }) => {
                    const newFilters = [...state]
                    newFilters[index] = { key, value, operator, type }
                    return newFilters
                },
                [actions.setFilters]: (_, { filters }) => filters,
                [actions.newFilter]: (state) => {
                    return [...state, {}]
                },
                [actions.remove]: (state, { index }) => {
                    const newState = state.filter((_, i) => i !== index)
                    if (newState.length === 0) {
                        return [{}]
                    }
                    if (Object.keys(newState[newState.length - 1]).length !== 0) {
                        return [...newState, {}]
                    }
                    return newState
                },
            },
        ],
    }),

    listeners: ({ actions, props, values }) => ({
        // Only send update if value is set to something
        [actions.setFilter]: ({ value }) => value && actions.update(),
        [actions.remove]: () => actions.update(),
        [actions.update]: () => {
            const cleanedFilters = [...values.filters].filter((property) => property.key)

            // If the last item has a key, we need to add a new empty filter so the button appears
            if (values.filters[values.filters.length - 1].key) {
                actions.newFilter()
            }
            if (props.onChange) {
                if (cleanedFilters.length === 0) {
                    return props.onChange([])
                }
                props.onChange(cleanedFilters)
            } else {
                const { properties, ...searchParams } = router.values.searchParams // eslint-disable-line
                const { pathname } = router.values.location

                searchParams.properties = cleanedFilters

                if (!objectsEqual(properties, cleanedFilters)) {
                    router.actions.push(pathname, searchParams)
                }
            }
        },
    }),

    urlToAction: ({ actions, values, props }) => ({
        '*': (_, { properties }) => {
            if (props.onChange) {
                return
            }

            let filters
            try {
                filters = values.filters
            } catch (error) {
                // since this is a catch-all route, this code might run during or after the logic was unmounted
                // if we have an error accessing the filter value, the logic is gone and we should return
                return
            }
            properties = parseProperties(properties)

            if (!objectsEqual(properties || {}, filters)) {
                // {} adds an empty row, which shows 'New Filter'
                actions.setFilters(properties ? [...properties, {}] : [{}])
            }
        },
    }),

    events: ({ actions, props }) => ({
        afterMount: () => {
            actions.newFilter()
            actions.loadPersonProperties()
            // TODO: Supporting event properties in sessions is temporarily unsupported (context https://github.com/PostHog/posthog/issues/2735)
            if (props.endpoint !== 'person' && props.endpoint !== 'sessions') {
                actions.setProperties(userLogic.values.eventProperties)
            }
        },
    }),
})
