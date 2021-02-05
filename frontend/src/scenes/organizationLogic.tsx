import { kea } from 'kea'
import api from 'lib/api'
import { organizationLogicType } from './organizationLogicType'
import { OrganizationType, PersonalizationData } from '~/types'

export interface OrganizationUpdatePayload {
    name?: string
    personalization?: PersonalizationData
    setup_section_2_completed?: boolean
}

export const organizationLogic = kea<organizationLogicType<OrganizationType, PersonalizationData>>({
    actions: {
        updateCompleted: (payload) => ({ payload }), // Triggered after an organization update is completed;
    },
    loaders: ({ actions }) => ({
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
                updateOrganization: async (payload: OrganizationUpdatePayload) => {
                    const response = await api.update('api/organizations/@current', payload)
                    actions.updateCompleted({ payload, response })
                    return response
                },
            },
        ],
    }),
    listeners: {
        createOrganizationSuccess: () => {
            window.location.href = '/organization/members'
        },
    },
    events: ({ actions }) => ({
        afterMount: [actions.loadCurrentOrganization],
    }),
})
