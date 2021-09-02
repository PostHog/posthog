import { kea } from 'kea'
import { groupPropertiesModelType } from './groupPropertiesModelType'
import api from 'lib/api'
import { PersonProperty } from '~/types'

export const groupPropertiesModel = kea<groupPropertiesModelType>({
    key: (props) => props.typeId,
    loaders: ({ props }) => ({
        groupProperties: [
            [] as Array<PersonProperty>,
            {
                // :TODO: Better url
                loadGroupProperties: async () =>
                    await api.get(`api/projects/@current/group_types/properties?type_id=${props.typeId}`),
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadGroupProperties,
    }),
})
