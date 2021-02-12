import { kea } from 'kea'
import api from 'lib/api'
import { organizationLogicType } from './organizationLogicType'
import { OrganizationType, PersonalizationData } from '~/types'
import { toast } from 'react-toastify'
import { userLogic } from './userLogic'
import { teamLogic } from './teamLogic'

interface OrganizationUpdatePayload {
    name?: string
    personalization?: PersonalizationData
}

export const organizationLogic = kea<organizationLogicType<OrganizationType, PersonalizationData>>({
    actions: {
        deleteCurrentOrganization: true,
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
                createOrganization: async (name: string) => {
                    const result = await api.create('api/organizations/', { name })
                    teamLogic.actions.loadCurrentTeam()
                    userLogic.actions.loadUser()
                    return result
                },
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
    listeners: ({ values }) => ({
        createOrganizationSuccess: () => {
            window.location.href = '/organization/members'
        },
        renameCurrentOrganizationSuccess: () => {
            toast.success('Organization has been renamed')
        },
        deleteCurrentOrganization: async () => {
            if (values.currentOrganization) {
                toast(`Deleting organization ${values.currentOrganization.name}…`)
                await api.delete(`api/organizations/${values.currentOrganization.id}`)
                location.reload()
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadCurrentOrganization],
    }),
})
