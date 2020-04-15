import { kea } from 'kea'
import api from '../../../lib/api'
import { userLogic } from 'scenes/userLogic'

export const propertyFilterLogic = kea({
    key: props => props.onChange,
    connect: {
        values: [userLogic, ['eventProperties']],
    },
    actions: () => ({
        loadEventProperties: true,
        setProperties: properties => ({ properties }),
        update: filters => ({ filters }),
        setInitial: filters => ({ filters }),
        setFilter: (index, key, value) => ({ index, key, value }),
        newFilter: true,
        remove: index => ({ index }),
    }),

    loaders: ({ values }) => ({
        properties: {
            loadPeopleProperties: async () => {
                return await api.get('api/person/properties')
            },
        },
    }),

    reducers: ({ actions, values }) => ({
        properties: [
            [],
            {
                [actions.loadPeoplePropertiesSuccess]: (_, { properties }) =>
                    properties.map(property => ({
                        label: property.name,
                        value: property.name,
                    })),
                [actions.setProperties]: (_, { properties }) => properties,
            },
        ],
        filters: [
            [],
            {
                [actions.setInitial]: (_, { filters }) => {
                    if (!filters) return []
                    return Object.entries(filters).map(([key, value]) => ({ [key]: value }))
                },
                [actions.setFilter]: (filters, { index, key, value }) => {
                    const newFilters = [...filters]
                    newFilters[index] = { [key]: value }
                    return newFilters
                },
                [actions.newFilter]: filters => {
                    return [...filters, {}]
                },
                [actions.remove]: (filters, { index }) => {
                    return filters.filter((_, i) => i !== index)
                },
            },
        ],
    }),
    listeners: ({ actions, props, values }) => ({
        [actions.setFilter]: () => actions.update(),
        [actions.remove]: () => actions.update(),
        [actions.update]: (_, { filters }) => {
            let dict = values.filters.reduce((result, item) => ({ ...result, ...item }))
            props.onChange(dict)
        },
    }),
    events: ({ actions, props, selectors }) => ({
        afterMount: () => {
            actions.setInitial(props.propertyFilters)
            if (props.endpoint == 'person') {
                actions.loadPeopleProperties()
            } else {
                actions.setProperties(selectors.eventProperties())
            }
        },
    }),
})
