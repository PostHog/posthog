import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api, { ApiConfig } from 'lib/api'
import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isUserLoggedIn } from 'lib/utils'
import { getAppContext } from 'lib/utils/getAppContext'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AvailableFeature, OrganizationType } from '~/types'

import type { organizationLogicType } from './organizationLogicType'
import { urls } from './urls'
import { userLogic } from './userLogic'

export type OrganizationUpdatePayload = Partial<
    Pick<
        OrganizationType,
        'name' | 'logo_media_id' | 'is_member_join_email_enabled' | 'enforce_2fa' | 'is_ai_data_processing_approved'
    >
>

export const organizationLogic = kea<organizationLogicType>([
    path(['scenes', 'organizationLogic']),
    actions({
        deleteOrganization: (organization: OrganizationType) => ({ organization }),
        deleteOrganizationSuccess: true,
        deleteOrganizationFailure: true,
    }),
    connect([userLogic]),
    reducers({
        organizationBeingDeleted: [
            null as OrganizationType | null,
            {
                deleteOrganization: (_, { organization }) => organization,
                deleteOrganizationSuccess: () => null,
                deleteOrganizationFailure: () => null,
            },
        ],
        migrateAccessControlVersionLoading: [
            false,
            {
                migrateAccessControlVersion: () => true,
                migrateAccessControlVersionSuccess: () => false,
                migrateAccessControlVersionFailure: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
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
                    // Check if re-authentication is required, if so, await its completion (or failure)
                    await timeSensitiveAuthenticationLogic.findMounted()?.asyncActions.checkReauthentication()
                    const updatedOrganization = await api.update(
                        `api/organizations/${values.currentOrganization.id}`,
                        payload
                    )
                    userLogic.actions.loadUser()
                    return updatedOrganization
                },
                completeOnboarding: async () => await api.create('api/organizations/@current/onboarding/', {}),
                migrateAccessControlVersion: async () => {
                    await api.create(`api/organizations/${values.currentOrganization?.id}/migrate_access_control/`, {})
                    window.location.reload()
                    return values.currentOrganization // Return current organization state since the page will reload anyway
                },
            },
        ],
    })),
    selectors({
        hasTagging: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.TAGGING),
        ],
        isCurrentOrganizationUnavailable: [
            (s) => [s.currentOrganization, s.currentOrganizationLoading],
            (currentOrganization, currentOrganizationLoading): boolean =>
                !currentOrganization?.membership_level && !currentOrganizationLoading,
        ],
        projectCreationForbiddenReason: [
            (s) => [s.currentOrganization],
            (currentOrganization): string | null =>
                !currentOrganization?.membership_level ||
                currentOrganization.membership_level < OrganizationMembershipLevel.Admin
                    ? 'You need to be an organization admin or above to create new projects.'
                    : null,
        ],
        isAdminOrOwner: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean | null =>
                !!(
                    currentOrganization?.membership_level &&
                    [OrganizationMembershipLevel.Admin, OrganizationMembershipLevel.Owner].includes(
                        currentOrganization.membership_level
                    )
                ),
        ],
    }),
    listeners(({ actions }) => ({
        loadCurrentOrganizationSuccess: ({ currentOrganization }) => {
            if (currentOrganization) {
                ApiConfig.setCurrentOrganizationId(currentOrganization.id)
            }
        },
        createOrganizationSuccess: () => {
            sidePanelStateLogic.findMounted()?.actions.closeSidePanel()
            window.location.href = urls.products()
        },
        updateOrganizationSuccess: () => {
            lemonToast.success('Organization updated successfully!')
        },
        deleteOrganization: async ({ organization }) => {
            try {
                await api.delete(`api/organizations/${organization.id}`)
                router.actions.push(router.values.currentLocation.pathname, 'organizationDeleted=true')
                location.reload()
                actions.deleteOrganizationSuccess()
            } catch {
                actions.deleteOrganizationFailure()
            }
        },
    })),
    afterMount(({ actions }) => {
        const appContext = getAppContext()
        const contextualOrganization = appContext?.current_user?.organization
        if (contextualOrganization) {
            // If app context is available (it should be practically always) we can immediately know currentOrganization
            actions.loadCurrentOrganizationSuccess(contextualOrganization)
        } else {
            // If app context is not available, a traditional request is needed
            actions.loadCurrentOrganization()
        }
    }),
])
