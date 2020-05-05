import { kea } from 'kea'
import api from '../../../lib/api'
import { userLogic } from 'scenes/userLogic'
import { addUrlQuestion, fromParams, toParams } from 'lib/utils'
import { router } from 'kea-router'

export const propertyFilterLogic = kea({
    key: props => props.pageKey,

    actions: () => ({
        loadEventProperties: true,
        setProperties: properties => ({ properties }),
        update: filters => ({ filters }),
        setFilter: (index, key, value) => ({ index, key, value }),
        setFilters: filters => ({ filters }),
        newFilter: true,
        remove: index => ({ index }),
    }),

    loaders: () => ({
        properties: {
            loadPeopleProperties: async () => {
                return (await api.get('api/person/properties')).map(property => ({
                    label: property.name,
                    value: property.name,
                }))
            },
        },
    }),

    reducers: ({ actions, props }) => ({
        properties: [
            [],
            {
                [actions.loadPeoplePropertiesSuccess]: (_, { properties }) => properties,
                [actions.setProperties]: (_, { properties }) => properties,
            },
        ],
        filters: [
            props.propertyFilters
                ? Object.entries(props.propertyFilters).map(([key, value]) => ({ [key]: value }))
                : [],
            {
                [actions.setFilter]: (state, { index, key, value }) => {
                    const newFilters = [...state]
                    newFilters[index] = { [key]: value }
                    return newFilters
                },
                [actions.setFilters]: (_, { filters }) => filters,
                [actions.newFilter]: state => {
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
            if (props.onChange) {
                if (values.filters.length === 0) {
                    actions.newFilter()
                    return props.onChange({})
                }
                if (Object.keys(values.filters[values.filters.length - 1]).length !== 0) actions.newFilter()
                let dict = values.filters.reduce((result, item) => ({ ...result, ...item }))
                props.onChange(dict)
            } else {
                const { filters } = values
                const { properties: _, ...urlParams } = fromParams()
                if (filters.filter(f => Object.keys(f).length > 0).length > 0) {
                    urlParams.properties = filters.reduce((result, item) => ({ ...result, ...item }))
                }
                const newUrl = addUrlQuestion(toParams(urlParams))
                const { search, pathname } = router.values.location
                if (search !== newUrl) {
                    router.actions.push(`${pathname}${newUrl}`)
                }
            }
        },
    }),

    urlToAction: ({ actions, values, props }) => ({
        '*': () => {
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

            const urlFilters = fromParams()

            if (urlFilters.properties !== JSON.stringify(filters)) {
                const newFilters = urlFilters.properties ? JSON.parse(urlFilters.properties) : {}
                const mappedFilters = Object.entries(newFilters).map(([key, value]) => ({ [key]: value }))
                actions.setFilters([...mappedFilters, {}])
            }
        },
    }),

    events: ({ actions, props, values }) => ({
        afterMount: () => {
            actions.newFilter()
            if (props.endpoint === 'person') {
                actions.loadPeopleProperties()
            } else {
                actions.setProperties(userLogic.values.eventProperties)
            }
        },
    }),
})
