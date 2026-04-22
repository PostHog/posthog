import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api, { ApiConfig, ApiError } from 'lib/api'
import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'
import { OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isUserLoggedIn } from 'lib/utils'
import { getAppContext } from 'lib/utils/getAppContext'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { OrganizationType } from '~/types'

import type { organizationLogicType } from './organizationLogicType'
import { urls } from './urls'
import { userLogic } from './userLogic'

export type OrganizationUpdatePayload = Partial<
    Pick<
        OrganizationType,
        | 'name'
        | 'logo_media_id'
        | 'enforce_2fa'
        | 'members_can_invite'
        | 'members_can_use_personal_api_keys'
        | 'is_ai_data_processing_approved'
        | 'default_experiment_stats_method'
        | 'allow_publicly_shared_resources'
        | 'default_role_id'
        | 'default_anonymize_ips'
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
        deleteOrganizationFailure: (error: string) => ({ error }),
    }),
    connect(() => ({
        values: [userLogic, ['hasAvailableFeature']],
        actions: [userLogic, ['loadUser'], router, ['locationChanged']],
    })),
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
                createOrganization: async (name: string) => {
                    await timeSensitiveAuthenticationLogic.findMounted()?.asyncActions.checkReauthentication()
                    return await api.create('api/organizations/', { name })
                },
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
                completeOnboarding: async () =>
                    await api.create(`api/organizations/${values.currentOrganization!.id}/onboarding/`, {}),
                migrateAccessControlVersion: async () => {
                    await api.create(`api/organizations/${values.currentOrganization!.id}/migrate_access_control/`, {})
                    window.location.reload()
                    return values.currentOrganization // Return current organization state since the page will reload anyway
                },
            },
        ],
    })),
    selectors({
        currentOrganizationId: [
            (s) => [s.currentOrganization],
            (currentOrganization): string => {
                if (!currentOrganization || !currentOrganization.id) {
                    // TODO: Fix callers that access currentOrganizationId before the organization is loaded,
                    // then restore the throw. Temporarily falling back to "@current" to avoid crashes.
                    posthog.captureException(new Error('currentOrganizationId accessed before organization loaded'), {
                        severity: 'warning',
                        tag: 'selector_accessed_before_loaded',
                    })
                    return '@current'
                }
                return currentOrganization.id
            },
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
        isNotActiveReason: [
            (s) => [s.currentOrganization],
            (currentOrganization): string | null => currentOrganization?.is_not_active_reason ?? null,
        ],
    }),
    listeners(({ actions, values }) => ({
        loadCurrentOrganizationSuccess: ({ currentOrganization }) => {
            if (currentOrganization) {
                ApiConfig.setCurrentOrganizationId(currentOrganization.id)
            }
        },
        locationChanged: ({ pathname }) => {
            // Redirect to pending deletion page if organization deletion is in progress
            if (values.currentOrganization?.is_pending_deletion && pathname !== urls.organizationPendingDeletion()) {
                router.actions.replace(urls.organizationPendingDeletion())
                return
            }
            // Redirect to deactivated page if organization is inactive (client-side navigation)
            if (values.currentOrganization?.is_active === false && pathname !== urls.organizationDeactivated()) {
                router.actions.replace(urls.organizationDeactivated())
            }
        },
        createOrganizationSuccess: () => {
            sidePanelStateLogic.findMounted()?.actions.closeSidePanel()
            window.location.href = urls.onboarding()
        },
        updateOrganizationSuccess: () => {
            lemonToast.success('Organization updated successfully!')
        },
        deleteOrganization: async ({ organizationId, redirectPath }) => {
            try {
                await api.delete(`api/organizations/${organizationId}`)
                actions.deleteOrganizationSuccess({ redirectPath })
            } catch (e) {
                const apiError = e as ApiError
                actions.deleteOrganizationFailure(apiError.detail || 'Error deleting organization')
            }
        },
        deleteOrganizationSuccess: ({ redirectPath }) => {
            lemonToast.success('Organization deletion has been initiated', {
                toastId: 'deleteOrganization',
            })

            // When deleting an org as part of the delete-account flow, skip the
            // page reload so the user stays in the modal. The org deletion is
            // async, so a reload would still show the org in the list.
            if (redirectPath === urls.settings('user-danger-zone')) {
                return
            }

            // Reload the page — the middleware will redirect to the pending deletion screen
            location.reload()
        },
        deleteOrganizationFailure: ({ error }) => {
            lemonToast.error(error, {
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
