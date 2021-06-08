import { kea } from 'kea'
import { personPropertiesModelType } from './personPropertiesModelType'
import api from 'lib/api'
import { PersonProperty } from 'scenes/sessions/filters/sessionsFiltersLogic'

export const personPropertiesModel = kea<personPropertiesModelType<PersonProperty>>({
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
