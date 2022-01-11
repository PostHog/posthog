import { kea } from 'kea'
import { personPropertiesModelType } from './personPropertiesModelType'
import api from 'lib/api'
import { PersonProperty } from '~/types'
import { getAppContext } from 'lib/utils/getAppContext'

export const personPropertiesModel = kea<personPropertiesModelType>({
    path: ['models', 'personPropertiesModel'],
    loaders: {
        personProperties: [
            [] as Array<PersonProperty>,
            {
                loadPersonProperties: async () => {
                    if (getAppContext()?.anonymous) {
                        // If user is anonymous (i.e. viewing a shared dashboard logged out), don't load authenticated stuff
                        return []
                    }
                    return await api.get('api/person/properties')
                },
            },
        ],
    },
    events: ({ actions }) => ({
        afterMount: actions.loadPersonProperties,
    }),
})
