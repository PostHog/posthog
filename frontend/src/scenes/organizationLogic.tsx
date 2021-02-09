import { kea } from 'kea'
import api from 'lib/api'
import { organizationLogicType } from './organizationLogicType'
import { OrganizationType, PersonalizationData } from '~/types'

interface OrganizationUpdatePayload {
    name?: string
    personalization?: PersonalizationData
}

export const organizationLogic = kea<organizationLogicType<OrganizationType, PersonalizationData>>({
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
                updateOrganization: async (payload: OrganizationUpdatePayload) =>
                    await api.update('api/organizations/@current', payload),
                completeOnboarding: async () => await api.create('api/organizations/@current/onboarding/', {}),
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
