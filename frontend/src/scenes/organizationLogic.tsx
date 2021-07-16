import { kea } from 'kea'
import api from 'lib/api'
import { organizationLogicType } from './organizationLogicType'
import { OrganizationType, PersonalizationData } from '~/types'
import { toast } from 'react-toastify'
import { userLogic } from './userLogic'

interface OrganizationUpdatePayload {
    name?: string
    personalization?: PersonalizationData
    domain_whitelist?: string[]
}

export const organizationLogic = kea<organizationLogicType<OrganizationUpdatePayload>>({
    actions: {
        deleteOrganization: (organization: OrganizationType) => ({ organization }),
        deleteOrganizationSuccess: true,
        deleteOrganizationFailure: true,
    },
    reducers: {
        organizationBeingDeleted: [
            null as OrganizationType | null,
            {
                deleteOrganization: (_, { organization }) => organization,
                deleteOrganizationSuccess: () => null,
                deleteOrganizationFailure: () => null,
            },
        ],
    },
    loaders: ({ values }) => ({
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
                renameCurrentOrganization: async (newName: string) => {
                    if (!values.currentOrganization) {
                        throw new Error('Current organization has not been loaded yet, so it cannot be renamed!')
                    }
                    const renamedOrganization = (await api.update(
                        `api/organizations/${values.currentOrganization.id}`,
                        {
                            name: newName,
                        }
                    )) as OrganizationType
                    userLogic.actions.loadUser()
                    return renamedOrganization
                },
                completeOnboarding: async () => await api.create('api/organizations/@current/onboarding/', {}),
            },
        ],
    }),
    listeners: ({ actions }) => ({
        createOrganizationSuccess: () => {
            window.location.href = '/organization/members'
        },
        renameCurrentOrganizationSuccess: () => {
            toast.success('Organization has been renamed')
        },
        updateOrganizationSuccess: () => {
            toast.success('Your configuration has been saved!')
        },
        deleteOrganization: async ({ organization }) => {
            try {
                await api.delete(`api/organizations/${organization.id}`)
                location.reload()
                actions.deleteOrganizationSuccess()
            } catch {
                actions.deleteOrganizationFailure()
            }
        },
        deleteOrganizationSuccess: () => {
            toast.success('Organization has been deleted')
        },
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadCurrentOrganization],
    }),
})
