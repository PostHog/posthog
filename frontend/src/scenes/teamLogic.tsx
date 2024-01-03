import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { ApiConfig } from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { IconSwapHoriz } from 'lib/lemon-ui/icons'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getPropertyLabel } from 'lib/taxonomy'
import { identifierToHuman, isUserLoggedIn, resolveWebhookService } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { getAppContext } from 'lib/utils/getAppContext'

import { CorrelationConfigType, PropertyOperator, TeamPublicType, TeamType } from '~/types'

import { organizationLogic } from './organizationLogic'
import type { teamLogicType } from './teamLogicType'
import { userLogic } from './userLogic'

const parseUpdatedAttributeName = (attr: string | null): string => {
    if (attr === 'slack_incoming_webhook') {
        return 'Webhook'
    }
    if (attr === 'app_urls') {
        return 'Authorized URLs'
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
        actions: [userLogic, ['loadUser']],
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
                        return await api.get('api/projects/@current')
                    } catch {
                        return null
                    }
                },
                updateCurrentTeam: async (payload: Partial<TeamType>, breakpoint) => {
                    if (!values.currentTeam) {
                        throw new Error('Current team has not been loaded yet, so it cannot be updated!')
                    }

                    const patchedTeam = (await api.update(`api/projects/${values.currentTeam.id}`, payload)) as TeamType
                    breakpoint()

                    actions.loadUser()

                    /* Notify user the update was successful  */
                    const updatedAttribute = Object.keys(payload).length === 1 ? Object.keys(payload)[0] : null

                    let message: string
                    if (updatedAttribute === 'slack_incoming_webhook') {
                        message = payload.slack_incoming_webhook
                            ? `Webhook integration enabled – you should be seeing a message on ${resolveWebhookService(
                                  payload.slack_incoming_webhook
                              )}`
                            : 'Webhook integration disabled'
                    } else if (
                        updatedAttribute === 'completed_snippet_onboarding' ||
                        updatedAttribute === 'has_completed_onboarding_for'
                    ) {
                        message = "Congrats! You're now ready to use PostHog."
                    } else {
                        message = `${parseUpdatedAttributeName(updatedAttribute)} updated successfully!`
                    }

                    Object.keys(payload).map((property) => {
                        eventUsageLogic.findMounted()?.actions?.reportTeamSettingChange(property, payload[property])
                    })

                    if (!window.location.pathname.match(/\/(onboarding|products)/)) {
                        lemonToast.success(message)
                    }

                    return patchedTeam
                },
                createTeam: async ({ name, is_demo }: { name: string; is_demo: boolean }): Promise<TeamType> =>
                    await api.create('api/projects/', { name, is_demo }),
                resetToken: async () => await api.update(`api/projects/${values.currentTeamId}/reset_token`, {}),
            },
        ],
    })),
    selectors(() => ({
        currentTeamId: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): number | null => (currentTeam ? currentTeam.id : null),
        ],
        isCurrentTeamUnavailable: [
            (selectors) => [selectors.currentTeam, selectors.currentTeamLoading],
            // If project has been loaded and is still null, it means the user just doesn't have access.
            (currentTeam, currentTeamLoading): boolean =>
                !currentTeam?.effective_membership_level && !currentTeamLoading,
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
                !!currentTeam?.effective_membership_level &&
                currentTeam.effective_membership_level >= OrganizationMembershipLevel.Admin,
        ],
        testAccountFilterWarningLabels: [
            (selectors) => [selectors.currentTeam],
            (currentTeam) => {
                if (!currentTeam) {
                    return null
                }
                const positiveFilterOperators = [
                    PropertyOperator.Exact,
                    PropertyOperator.IContains,
                    PropertyOperator.Regex,
                    PropertyOperator.IsSet,
                ]
                const positiveFilters = []
                for (const filter of currentTeam.test_account_filters || []) {
                    if (
                        'operator' in filter &&
                        !!filter.operator &&
                        positiveFilterOperators.includes(filter.operator)
                    ) {
                        positiveFilters.push(filter)
                    }
                }

                return positiveFilters.map((filter) => {
                    if (!!filter.type && !!filter.key) {
                        // person properties can be checked for a label as if they were event properties
                        // so, we can check each acceptable type and see if it returns a value
                        return (
                            getPropertyLabel(filter.key, 'event') ||
                            getPropertyLabel(filter.key, 'element') ||
                            filter.key
                        )
                    } else {
                        return filter.key
                    }
                })
            },
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
    })),
    listeners(({ actions }) => ({
        loadCurrentTeamSuccess: ({ currentTeam }) => {
            if (currentTeam) {
                ApiConfig.setCurrentTeamId(currentTeam.id)
            }
        },
        createTeamSuccess: () => {
            organizationLogic.actions.loadCurrentOrganization()
        },
        deleteTeam: async ({ team }) => {
            try {
                await api.delete(`api/projects/${team.id}`)
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
    afterMount(({ actions }) => {
        const appContext = getAppContext()
        const currentTeam = appContext?.current_team
        const switchedTeam = appContext?.switched_team
        if (switchedTeam) {
            lemonToast.info(<>You've switched to&nbsp;project {currentTeam?.name}</>, {
                button: {
                    label: 'Switch back',
                    action: () => userLogic.actions.updateCurrentTeam(switchedTeam),
                },
                icon: <IconSwapHoriz />,
            })
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
