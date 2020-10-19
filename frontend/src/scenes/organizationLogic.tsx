import { kea } from 'kea'
import api from 'lib/api'
import { organizationLogicType } from 'types/scenes/organizationLogicType'
import { OrganizationType } from '~/types'

export const organizationLogic = kea<organizationLogicType>({
    loaders: {
        currentOrganization: [
            null as OrganizationType | null,
            {
                loadCurrentOrganization: async () => await api.get('api/organizations/@current'),
                createOrganization: async (name: string) => await api.create('api/organizations/', { name }),
            },
        ],
    },
    listeners: {
        createOrganizationSuccess: () => {
            window.location.href = '/organization/members'
        },
    },
    events: ({ actions }) => ({
        afterMount: [actions.loadCurrentOrganization],
    }),
})
