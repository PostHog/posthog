import { kea } from 'kea'
import api from 'lib/api'

export const propertiesModel = kea({
    loaders: () => ({
        properties: {
            __default: [],
            loadProperties: async () => {
                const properties = await api.get('api/event/properties')
                return properties.map(property => ({
                    label: property.name,
                    value: property.name,
                }))
            },
        },
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadProperties,
    }),
})
