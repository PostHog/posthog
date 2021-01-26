import { kea } from 'kea'
import api from 'lib/api'
import { organizationLogicType } from './organizationLogicType'
import { OrganizationType } from '~/types'

export const organizationLogic = kea<organizationLogicType<OrganizationType>>({
    loaders: {
        currentOrganization: [
            null as OrganizationType | null,
            {
                loadCurrentOrganization: async () => {
                    try {
                        return await api.get('api/organizations/@current')
                    } catch {
                        return null
                    }
                },
                createOrganization: async (name: string) => await api.create('api/organizations/', { name }),
                updateOrganization: async ({
                    name,
                    completed_personalization,
                }: {
                    name?: string
                    completed_personalization?: boolean
                }) => await api.update('api/organizations/@current', { name, completed_personalization }),
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
