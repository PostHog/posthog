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
                updateOrganization: async (payload: { name?: string; personalization?: Record<string, any> }) =>
                    await api.update('api/organizations/@current', payload),
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
