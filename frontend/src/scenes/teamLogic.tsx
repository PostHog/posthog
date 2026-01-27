import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiConfig } from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { IconSwapHoriz } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { identifierToHuman, isUserLoggedIn, resolveWebhookService } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DEFAULT_CURRENCY } from 'lib/utils/geography/currency'
import { getAppContext } from 'lib/utils/getAppContext'
import {
    type ProductCrossSellProperties,
    type ProductIntentProperties,
    addProductIntent,
    addProductIntentForCrossSell,
} from 'lib/utils/product-intents'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { CurrencyCode, CustomerAnalyticsConfig, ProductKey } from '~/queries/schema/schema-general'
import { CorrelationConfigType, ProjectType, TeamPublicType, TeamType } from '~/types'

import { organizationLogic } from './organizationLogic'
import { projectLogic } from './projectLogic'
import type { teamLogicType } from './teamLogicType'
import { userLogic } from './userLogic'

const parseUpdatedAttributeName = (attr: keyof TeamType | null): string => {
    if (attr === 'slack_incoming_webhook') {
        return 'Webhook'
    }
    if (attr === 'app_urls') {
        return 'Authorized URLs'
    }

    if (attr === 'web_analytics_pre_aggregated_tables_enabled') {
        return 'New query engine'
    }

    if (attr === 'session_recording_minimum_duration_milliseconds') {
        return 'Session recording minimum duration'
    }

    return attr ? identifierToHuman(attr) : 'Project'
}

/** Return whether the provided value is a full TeamType object that's only available when authenticated. */
export function isAuthenticatedTeam(team: TeamType | TeamPublicType | undefined | null): team is TeamType {
    return !!team && 'api_token' in team
}

export interface FrequentMistakeAdvice {
    key: string
    type: 'event' | 'person'
    fix: string
}

export const teamLogic = kea<teamLogicType>([
    path(['scenes', 'teamLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProject'], featureFlagLogic, ['featureFlags']],
        actions: [
            userLogic,
            ['loadUser', 'switchTeam'],
            organizationLogic,
            ['loadCurrentOrganization'],
            customProductsLogic,
            ['loadCustomProducts'],
        ],
    })),
    actions({
        deleteTeam: (team: TeamType) => ({ team }),
        deleteTeamSuccess: true,
        deleteTeamFailure: true,
    }),
    reducers({
        teamBeingDeleted: [
            null as TeamType | null,
            {
                deleteTeam: (_, { team }) => team,
                deleteTeamSuccess: () => null,
                deleteTeamFailure: () => null,
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        currentTeam: [
            null as TeamType | TeamPublicType | null,
            {
                loadCurrentTeam: async () => {
                    if (!isUserLoggedIn()) {
                        // If user is anonymous (i.e. viewing a shared dashboard logged out), don't load authenticated stuff
                        return null
                    }

                    try {
                        return await api.get('api/environments/@current')
                    } catch {
                        return values.currentTeam
                    }
                },
                updateCurrentTeam: async (payload: Partial<TeamType>, breakpoint) => {
                    if (!values.currentTeam) {
                        throw new Error('Current team has not been loaded yet, so it cannot be updated!')
                    }

                    // session replay config is nested, so we need to make sure we don't overwrite config
                    if (payload.session_replay_config) {
                        payload.session_replay_config = {
                            ...values.currentTeam.session_replay_config,
                            ...payload.session_replay_config,
                        }
                    }

                    const promises: [Promise<TeamType>, Promise<ProjectType> | undefined] = [
                        api.update(`api/environments/${values.currentTeam.id}`, payload),
                        undefined,
                    ]
                    if (
                        Object.keys(payload).length === 1 &&
                        payload.name &&
                        values.currentProject &&
                        !values.featureFlags[FEATURE_FLAGS.ENVIRONMENTS]
                    ) {
                        // If we're only updating the name and the user doesn't have access to the environments feature,
                        // update the project name as well, for 100% equivalence
                        promises[0] = api.update(`api/projects/${values.currentProject.id}`, { name: payload.name })
                    }
                    const [patchedTeam] = await Promise.all(promises)
                    breakpoint()

                    // We need to reload current org (which lists its teams) in organizationLogic
                    actions.loadCurrentOrganization()

                    /* Notify user the update was successful  */
                    const updatedAttribute =
                        Object.keys(payload).length === 1 ? (Object.keys(payload)[0] as keyof TeamType) : null

                    let message: string
                    if (updatedAttribute === 'slack_incoming_webhook') {
                        message = payload.slack_incoming_webhook
                            ? `Webhook integration enabled – you should be seeing a message on ${resolveWebhookService(
                                  payload.slack_incoming_webhook
                              )}`
                            : 'Webhook integration disabled'
                    } else if (updatedAttribute === 'feature_flag_confirmation_enabled') {
                        message = payload.feature_flag_confirmation_enabled
                            ? 'Feature flag confirmation enabled'
                            : 'Feature flag confirmation disabled'
                    } else if (updatedAttribute === 'default_evaluation_contexts_enabled') {
                        message = payload.default_evaluation_contexts_enabled
                            ? 'Default evaluation contexts enabled'
                            : 'Default evaluation contexts disabled'
                    } else if (updatedAttribute === 'require_evaluation_contexts') {
                        message = payload.require_evaluation_contexts
                            ? 'Require evaluation contexts enabled'
                            : 'Require evaluation contexts disabled'
                    } else if (
                        updatedAttribute === 'completed_snippet_onboarding' ||
                        updatedAttribute === 'has_completed_onboarding_for'
                    ) {
                        message = "Congrats! You're now ready to use PostHog."
                    } else {
                        message = `${parseUpdatedAttributeName(updatedAttribute)} updated successfully!`
                    }

                    Object.keys(payload).map((property) => {
                        eventUsageLogic
                            .findMounted()
                            ?.actions?.reportTeamSettingChange(property, payload[property as keyof TeamType])
                    })

                    const isUpdatingOnboardingTasks = Object.keys(payload).every((key) => key === 'onboarding_tasks')

                    if (!window.location.pathname.match(/\/(onboarding|products)/) && !isUpdatingOnboardingTasks) {
                        lemonToast.success(message)
                    }

                    const setupLogic = globalSetupLogic.findMounted()
                    if (setupLogic) {
                        if (payload.autocapture_web_vitals_opt_in) {
                            setupLogic.actions.markTaskAsCompleted(SetupTaskId.SetUpWebVitals)
                        }
                        if (payload.session_recording_opt_in) {
                            setupLogic.actions.markTaskAsCompleted(SetupTaskId.SetupSessionRecordings)
                        }
                        if (payload.capture_console_log_opt_in) {
                            setupLogic.actions.markTaskAsCompleted(SetupTaskId.EnableConsoleLogs)
                        }
                        if (
                            payload.session_recording_sample_rate ||
                            payload.session_recording_minimum_duration_milliseconds ||
                            payload.session_recording_linked_flag ||
                            payload.session_recording_network_payload_capture_config
                        ) {
                            setupLogic.actions.markTaskAsCompleted(SetupTaskId.ConfigureRecordingSettings)
                        }
                    }

                    return patchedTeam
                },
                createTeam: async ({ name, is_demo }: { name: string; is_demo: boolean }) => {
                    if (!values.currentProject) {
                        throw new Error(
                            'Environment could not be created, because the parent project has not been loaded yet!'
                        )
                    }
                    return await api.create(`api/projects/${values.currentProject.id}/environments/`, { name, is_demo })
                },
                // Project API Token
                resetToken: async () => await api.update(`api/environments/${values.currentTeamId}/reset_token`, {}),
                // Feature Flags Secure API Token
                rotateSecretToken: async () =>
                    await api.update(`api/environments/${values.currentTeamId}/rotate_secret_token`, {}),
                deleteSecretTokenBackup: async () =>
                    await api.update(`api/environments/${values.currentTeamId}/delete_secret_token_backup`, {}),
                /**
                 * If adding a product intent that also represents regular product usage, see explainer in posthog.models.product_intent.product_intent.py.
                 * Also, we refresh the list of custom products to show the possible new entry in the sidebar after we've added the intent.
                 */
                addProductIntent: async (properties: ProductIntentProperties) => {
                    const result = await addProductIntent(properties)
                    actions.loadCustomProducts()

                    return result
                },
                addProductIntentForCrossSell: async (properties: ProductCrossSellProperties) => {
                    const result = await addProductIntentForCrossSell(properties)
                    actions.loadCustomProducts()

                    return result
                },
                recordProductIntentOnboardingComplete: async ({ product_type }: { product_type: ProductKey }) => {
                    const result = await api.update(
                        `api/environments/${values.currentTeamId}/complete_product_onboarding`,
                        {
                            product_type,
                        }
                    )
                    actions.loadCustomProducts()

                    return result
                },
            },
        ],
    })),
    selectors(() => ({
        hasOnboardedAnyProduct: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): boolean => {
                if (
                    currentTeam &&
                    !currentTeam.completed_snippet_onboarding &&
                    !Object.keys(currentTeam.has_completed_onboarding_for || {}).length
                ) {
                    return false
                }
                return true
            },
        ],
        hasIngestedEvent: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): boolean => {
                return currentTeam?.ingested_event ?? false
            },
        ],
        currentTeamId: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): number | null => (currentTeam ? currentTeam.id : null),
        ],
        isCurrentTeamUnavailable: [
            (selectors) => [selectors.currentTeam, selectors.currentTeamLoading],
            // If project has been loaded and is still null, it means the user just doesn't have access.
            (currentTeam, currentTeamLoading): boolean =>
                (!currentTeam?.effective_membership_level || currentTeam.user_access_level === 'none') &&
                !currentTeamLoading,
        ],
        demoOnlyProject: [
            (selectors) => [selectors.currentTeam, organizationLogic.selectors.currentOrganization],
            (currentTeam, currentOrganization): boolean =>
                (currentTeam?.is_demo && currentOrganization?.teams && currentOrganization.teams.length == 1) || false,
        ],
        funnelCorrelationConfig: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): CorrelationConfigType => {
                return currentTeam?.correlation_config || {}
            },
        ],
        timezone: [(selectors) => [selectors.currentTeam], (currentTeam): string => currentTeam?.timezone || 'UTC'],
        /** 0 means Sunday, 1 means Monday. */
        weekStartDay: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): number => currentTeam?.week_start_day || 0,
        ],
        isTeamTokenResetAvailable: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): boolean =>
                (!!currentTeam?.effective_membership_level &&
                    currentTeam.effective_membership_level >= OrganizationMembershipLevel.Admin) ||
                currentTeam?.user_access_level === 'admin',
        ],
        testAccountFilterFrequentMistakes: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): FrequentMistakeAdvice[] => {
                if (!currentTeam) {
                    return []
                }
                const frequentMistakes: FrequentMistakeAdvice[] = []

                for (const filter of currentTeam.test_account_filters || []) {
                    if (filter.key === 'email' && filter.type === 'event') {
                        frequentMistakes.push({
                            key: 'email',
                            type: 'event',
                            fix: 'it is more common to filter email by person properties, not event properties',
                        })
                    }
                }
                return frequentMistakes
            },
        ],
        baseCurrency: [
            (selectors) => [selectors.currentTeam],
            (currentTeam: TeamType): CurrencyCode => currentTeam?.base_currency ?? DEFAULT_CURRENCY,
        ],
        customerAnalyticsConfig: [
            (s) => [s.currentTeam],
            (currentTeam: TeamType): CustomerAnalyticsConfig =>
                currentTeam?.customer_analytics_config ?? ({} as CustomerAnalyticsConfig),
        ],
    })),
    listeners(({ actions }) => ({
        loadCurrentTeamSuccess: ({ currentTeam }) => {
            if (currentTeam) {
                ApiConfig.setCurrentTeamId(currentTeam.id)
            }

            // Detect managed viewsets to mark them as completed in the product setup
            if (currentTeam?.managed_viewsets?.['revenue_analytics']) {
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.EnableRevenueAnalyticsViewset)
            }
        },
        updateCurrentTeamSuccess: () => {
            // Reload user after team update to keep user object in sync
            actions.loadUser()
        },
        createTeamSuccess: ({ currentTeam }) => {
            if (currentTeam) {
                actions.switchTeam(currentTeam.id)
            }
        },
        deleteTeam: async ({ team }) => {
            try {
                await api.delete(`api/environments/${team.id}`)
                location.reload()
                actions.deleteTeamSuccess()
            } catch {
                actions.deleteTeamFailure()
            }
        },
        deleteTeamSuccess: () => {
            lemonToast.success('Project has been deleted')
        },
    })),
    afterMount(({ actions, values }) => {
        const appContext = getAppContext()
        const currentTeam = appContext?.current_team
        const currentProject = appContext?.current_project
        const switchedTeam = appContext?.switched_team
        if (switchedTeam) {
            lemonToast.info(
                <>
                    You've switched to&nbsp;project{' '}
                    {values.featureFlags[FEATURE_FLAGS.ENVIRONMENTS]
                        ? `${currentProject?.name}, environment ${currentTeam?.name}`
                        : currentTeam?.name}
                </>,
                {
                    button: {
                        label: 'Switch back',
                        action: () => actions.switchTeam(switchedTeam),
                    },
                    icon: <IconSwapHoriz />,
                }
            )
        }

        if (currentTeam) {
            // If app context is available (it should be practically always) we can immediately know currentTeam
            actions.loadCurrentTeamSuccess(currentTeam)
        } else {
            // If app context is not available, a traditional request is needed
            actions.loadCurrentTeam()
        }
    }),
])
