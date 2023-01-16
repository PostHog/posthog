import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import api from 'lib/api'
import type { teamLogicType } from './teamLogicType'
import { CorrelationConfigType, PropertyOperator, TeamType } from '~/types'
import { userLogic } from './userLogic'
import { identifierToHuman, isUserLoggedIn, resolveWebhookService } from 'lib/utils'
import { organizationLogic } from './organizationLogic'
import { getAppContext } from '../lib/utils/getAppContext'
import { lemonToast } from 'lib/components/lemonToast'
import { IconSwapHoriz } from 'lib/components/icons'
import { loaders } from 'kea-loaders'
import { OrganizationMembershipLevel } from '../lib/constants'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { getPropertyLabel } from 'lib/components/PropertyKeyInfo'

const parseUpdatedAttributeName = (attr: string | null): string => {
    if (attr === 'slack_incoming_webhook') {
        return 'Webhook'
    }
    if (attr === 'app_urls') {
        return 'Authorized URLs'
    }
    return attr ? identifierToHuman(attr) : 'Project'
}

export const teamLogic = kea<teamLogicType>([
    path(['scenes', 'teamLogic']),
    connect({
        actions: [userLogic, ['loadUser']],
    }),
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
            null as TeamType | null,
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
                updateCurrentTeam: async (payload: Partial<TeamType>) => {
                    if (!values.currentTeam) {
                        throw new Error('Current team has not been loaded yet, so it cannot be updated!')
                    }
                    const patchedTeam = (await api.update(`api/projects/${values.currentTeam.id}`, payload)) as TeamType
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
                    } else if (updatedAttribute === 'completed_snippet_onboarding') {
                        message = "Congrats! You're now ready to use PostHog."
                    } else {
                        message = `${parseUpdatedAttributeName(updatedAttribute)} updated successfully!`
                    }

                    if (updatedAttribute) {
                        const updatedValue = Object.values(payload).length === 1 ? Object.values(payload)[0] : null
                        eventUsageLogic.findMounted()?.actions?.reportTeamSettingChange(updatedAttribute, updatedValue)
                    }

                    lemonToast.dismiss('updateCurrentTeam')
                    lemonToast.success(message, {
                        toastId: 'updateCurrentTeam',
                    })

                    return patchedTeam
                },
                createTeam: async ({ name, is_demo }: { name: string; is_demo: boolean }): Promise<TeamType> =>
                    await api.create('api/projects/', { name, is_demo }),
                resetToken: async () => await api.update(`api/projects/${values.currentTeamId}/reset_token`, {}),
            },
        ],
    })),
    selectors({
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
        pathCleaningFiltersWithNew: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): Record<string, any>[] => {
                return currentTeam?.path_cleaning_filters ? [...currentTeam.path_cleaning_filters, {}] : [{}]
            },
        ],
        funnelCorrelationConfig: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): CorrelationConfigType => {
                return currentTeam?.correlation_config || {}
            },
        ],
        timezone: [(selectors) => [selectors.currentTeam], (currentTeam): string => currentTeam?.timezone || 'UTC'],
        isTeamTokenResetAvailable: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): boolean =>
                !!currentTeam?.effective_membership_level &&
                currentTeam.effective_membership_level >= OrganizationMembershipLevel.Admin,
        ],
        testAccountFilterWarning: [
            (selectors) => [selectors.currentTeam],
            (currentTeam): JSX.Element | null => {
                if (!currentTeam) {
                    return null
                }
                const positiveFilterOperators = [
                    PropertyOperator.Exact,
                    PropertyOperator.IContains,
                    PropertyOperator.Regex,
                ]
                const positiveFilters = []
                for (const filter of currentTeam.test_account_filters) {
                    if (
                        'operator' in filter &&
                        !!filter.operator &&
                        positiveFilterOperators.includes(filter.operator)
                    ) {
                        positiveFilters.push(filter)
                    }
                }
                if (positiveFilters.length > 0) {
                    const labels = positiveFilters.map((filter) => {
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
                    return (
                        <>
                            <p>
                                Positive filters here mean only events or persons matching these filters will be
                                included. Internal and test account filters are normally excluding filters like does not
                                equal or does not contain.
                            </p>
                            <p>Positive filters are currently set for the following properties: </p>
                            <ul className={'list-disc'}>
                                {labels.map((l, i) => (
                                    <li key={i} className={'ml-4'}>
                                        {l}
                                    </li>
                                ))}
                            </ul>
                        </>
                    )
                } else {
                    return null
                }
            },
        ],
    }),
    listeners(({ actions }) => ({
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
    events(({ actions }) => ({
        afterMount: () => {
            const appContext = getAppContext()
            const contextualTeam = appContext?.current_team

            const switchedTeam = appContext?.switched_team
            if (switchedTeam) {
                lemonToast.info(<>You've switched to&nbsp;project {contextualTeam?.name}</>, {
                    button: {
                        label: 'Switch back',
                        action: () => userLogic.actions.updateCurrentTeam(switchedTeam),
                    },
                    icon: <IconSwapHoriz />,
                })
            }

            if (contextualTeam) {
                // If app context is available (it should be practically always) we can immediately know currentTeam
                actions.loadCurrentTeamSuccess(contextualTeam)
            } else {
                // If app context is not available, a traditional request is needed
                actions.loadCurrentTeam()
            }
        },
    })),
])
