import { kea } from 'kea'
import { personPropertiesModelType } from './personPropertiesModelType'
import api from 'lib/api'
import { PersonProperty, ProjectBasedLogicProps } from '~/types'

export const personPropertiesModel = kea<personPropertiesModelType>({
    props: {} as ProjectBasedLogicProps,
    key: (props) => props.teamId || '',
    loaders: {
        personProperties: [
            [] as Array<PersonProperty>,
            {
                loadPersonProperties: async () => await api.get('api/person/properties'),
            },
        ],
    },
    events: ({ actions, props }) => ({
        afterMount: () => props.teamId && actions.loadPersonProperties,
    }),
})
