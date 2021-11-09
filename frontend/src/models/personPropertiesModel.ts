import { kea } from 'kea'
import { personPropertiesModelType } from './personPropertiesModelType'
import api from 'lib/api'
import { PersonProperty } from '~/types'

export const personPropertiesModel = kea<personPropertiesModelType>({
    path: ['models', 'personPropertiesModel'],
    loaders: {
        personProperties: [
            [] as Array<PersonProperty>,
            {
                loadPersonProperties: async () => await api.get('api/person/properties'),
            },
        ],
    },
    events: ({ actions }) => ({
        afterMount: actions.loadPersonProperties,
    }),
})
