import { kea } from 'kea'
import api from '../../../lib/api'
import { userLogic } from 'scenes/userLogic'

export const propertyFilterLogic = kea({
    key: props => props.pageKey,
    connect: {
        values: [userLogic, ['eventProperties']],
    },
    actions: () => ({
        loadEventProperties: true,
        setProperties: properties => ({ properties }),
        update: filters => ({ filters }),
        setFilter: (index, key, value) => ({ index, key, value }),
        newFilter: true,
        remove: index => ({ index }),
    }),

    loaders: () => ({
        properties: {
            loadPeopleProperties: async () => {
                return await api.get('api/person/properties')
            },
        },
    }),

    reducers: ({ actions, props }) => ({
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
            props.propertyFilters
                ? Object.entries(props.propertyFilters).map(([key, value]) => ({ [key]: value }))
                : [],
            {
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
            if (props.endpoint == 'person') {
                actions.loadPeopleProperties()
            } else {
                actions.setProperties(selectors.eventProperties())
            }
        },
    }),
})
