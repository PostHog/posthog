import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api, { ApiConfig } from 'lib/api'
import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'
import { OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
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
        | 'name'
        | 'logo_media_id'
        | 'is_member_join_email_enabled'
        | 'enforce_2fa'
        | 'members_can_invite'
        | 'members_can_use_personal_api_keys'
        | 'is_ai_data_processing_approved'
        | 'default_experiment_stats_method'
        | 'allow_publicly_shared_resources'
        | 'default_role_id'
    >
>

export const organizationLogic = kea<organizationLogicType>([
    path(['scenes', 'organizationLogic']),
    actions({
        deleteOrganization: ({ organizationId, redirectPath }: { organizationId: string; redirectPath?: string }) => ({
            organizationId,
            redirectPath,
        }),
        deleteOrganizationSuccess: ({ redirectPath }: { redirectPath?: string }) => ({ redirectPath }),
        deleteOrganizationFailure: true,
    }),
    connect([userLogic]),
    reducers({
        organizationBeingDeleted: [
            null as string | null,
            {
                deleteOrganization: (_, { organizationId }) => organizationId,
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
        isCurrentOrganizationNew: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean => {
                const orgCreatedAt = currentOrganization?.created_at
                return orgCreatedAt ? dayjs().diff(dayjs(orgCreatedAt), 'month') < 3 : false
            },
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
        deleteOrganization: async ({ organizationId, redirectPath }) => {
            try {
                await api.delete(`api/organizations/${organizationId}`)
                actions.deleteOrganizationSuccess({ redirectPath })
            } catch {
                actions.deleteOrganizationFailure()
            }
        },
        deleteOrganizationSuccess: ({ redirectPath }) => {
            router.actions.replace(redirectPath ?? router.values.currentLocation.pathname, {
                ...router.values.searchParams,
                organizationDeleted: true,
            })

            lemonToast.success('Organization has been deleted', {
                toastId: 'deleteOrganization',
            })
            location.reload()
        },
        deleteOrganizationFailure: () => {
            lemonToast.error('Error deleting organization', {
                toastId: 'deleteOrganization',
            })
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
