import { kea } from 'kea'
import api from 'lib/api'
import type { organizationLogicType } from './organizationLogicType'
import { AvailableFeature, OrganizationType } from '~/types'
import { userLogic } from './userLogic'
import { getAppContext } from '../lib/utils/getAppContext'
import { OrganizationMembershipLevel } from '../lib/constants'
import { isUserLoggedIn } from 'lib/utils'
import { lemonToast } from 'lib/components/lemonToast'

export type OrganizationUpdatePayload = Partial<Pick<OrganizationType, 'name' | 'is_member_join_email_enabled'>>

export const organizationLogic = kea<organizationLogicType>({
    path: ['scenes', 'organizationLogic'],
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
    selectors: {
        hasDashboardCollaboration: [
            (s) => [s.currentOrganization],
            (currentOrganization) =>
                currentOrganization?.available_features?.includes(AvailableFeature.DASHBOARD_COLLABORATION),
        ],
        hasIngestionTaxonomy: [
            (s) => [s.currentOrganization],
            (currentOrganization) =>
                currentOrganization?.available_features?.includes(AvailableFeature.INGESTION_TAXONOMY),
        ],
        isCurrentOrganizationUnavailable: [
            (s) => [s.currentOrganization, s.currentOrganizationLoading],
            (currentOrganization, currentOrganizationLoading): boolean =>
                !currentOrganization?.membership_level && !currentOrganizationLoading,
        ],
        isProjectCreationForbidden: [
            (s) => [s.currentOrganization],
            (currentOrganization) =>
                !currentOrganization?.membership_level ||
                currentOrganization.membership_level < OrganizationMembershipLevel.Admin,
        ],
    },
    loaders: ({ values }) => ({
        currentOrganization: [
            null as OrganizationType | null,
            {
                loadCurrentOrganization: async () => {
                    if (!isUserLoggedIn()) {
                        // If user is anonymous (i.e. viewing a shared dashboard logged out), don't load authenticated stuff
                        return null
                    }
                    try {
                        return await api.get('api/organizations/@current')
                    } catch {
                        return null
                    }
                },
                createOrganization: async (name: string) => await api.create('api/organizations/', { name }),
                updateOrganization: async (payload: OrganizationUpdatePayload) => {
                    if (!values.currentOrganization) {
                        throw new Error('Current organization has not been loaded yet.')
                    }
                    const updatedOrganization = await api.update(
                        `api/organizations/${values.currentOrganization.id}`,
                        payload
                    )
                    userLogic.actions.loadUser()
                    return updatedOrganization
                },
                completeOnboarding: async () => await api.create('api/organizations/@current/onboarding/', {}),
            },
        ],
    }),
    listeners: ({ actions }) => ({
        createOrganizationSuccess: () => {
            window.location.href = '/organization/members'
        },
        updateOrganizationSuccess: () => {
            lemonToast.success('Your configuration has been saved')
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
            lemonToast.success('Organization has been deleted')
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            const appContext = getAppContext()
            const contextualOrganization = appContext?.current_user?.organization
            if (contextualOrganization) {
                // If app context is available (it should be practically always) we can immediately know currentOrganization
                actions.loadCurrentOrganizationSuccess(contextualOrganization)
            } else {
                // If app context is not available, a traditional request is needed
                actions.loadCurrentOrganization()
            }
        },
    }),
})
