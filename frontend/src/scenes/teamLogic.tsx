import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import React from 'react'
import api from 'lib/api'
import { teamLogicType } from './teamLogicType'
import { TeamType } from '~/types'
import { userLogic } from './userLogic'
import { identifierToHuman, isUserLoggedIn, resolveWebhookService } from 'lib/utils'
import { organizationLogic } from './organizationLogic'
import { getAppContext } from '../lib/utils/getAppContext'
import { lemonToast } from 'lib/components/lemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { IconSwapHoriz } from 'lib/components/icons'
import { loaders } from 'kea-loaders'

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
        actions: [eventUsageLogic, ['reportTeamHasIngestedEvents'], userLogic, ['loadUser']],
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
                    } else {
                        message = `${parseUpdatedAttributeName(updatedAttribute)} updated successfully!`
                    }

                    lemonToast.dismiss('updateCurrentTeam')
                    lemonToast.success(message, {
                        toastId: 'updateCurrentTeam',
                    })

                    return patchedTeam
                },
                createTeam: async (name: string): Promise<TeamType> => await api.create('api/projects/', { name }),
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
            (currentTeam): Partial<TeamType['correlation_config']> => {
                return currentTeam?.correlation_config || {}
            },
        ],
    }),
    listeners(({ actions, values }) => ({
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
        createTeamSuccess: () => {
            window.location.href = '/ingestion'
        },
        loadCurrentTeamSuccess: () => {
            // For Onboarding 1's experiment, we are tracking whether a team has ingested events on the client side
            // because experiments doesn't support this yet in other libraries
            if (values.currentTeam?.ingested_event) {
                actions.reportTeamHasIngestedEvents()
            }
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
