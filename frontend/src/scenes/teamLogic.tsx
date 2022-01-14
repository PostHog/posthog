import { kea } from 'kea'
import api from 'lib/api'
import { teamLogicType } from './teamLogicType'
import { TeamType } from '~/types'
import { userLogic } from './userLogic'
import { toast } from 'react-toastify'
import React from 'react'
import { identifierToHuman, isUserLoggedIn, resolveWebhookService } from 'lib/utils'
import { organizationLogic } from './organizationLogic'
import { getAppContext } from '../lib/utils/getAppContext'

const parseUpdatedAttributeName = (attr: string | null): string => {
    if (attr === 'slack_incoming_webhook') {
        return 'Webhook'
    }
    if (attr === 'app_urls') {
        return 'Authorized URLs'
    }
    return attr ? identifierToHuman(attr) : 'Project'
}

export const teamLogic = kea<teamLogicType>({
    path: ['scenes', 'teamLogic'],
    actions: {
        deleteTeam: (team: TeamType) => ({ team }),
        deleteTeamSuccess: true,
        deleteTeamFailure: true,
    },
    reducers: {
        teamBeingDeleted: [
            null as TeamType | null,
            {
                deleteTeam: (_, { team }) => team,
                deleteTeamSuccess: () => null,
                deleteTeamFailure: () => null,
            },
        ],
    },
    loaders: ({ values }) => ({
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
                    userLogic.actions.loadUser()

                    /* Notify user the update was successful  */
                    const updatedAttribute = Object.keys(payload).length === 1 ? Object.keys(payload)[0] : null

                    let description = "Your project's settings have been successfully updated. Click here to dismiss."

                    if (updatedAttribute === 'slack_incoming_webhook') {
                        description = payload.slack_incoming_webhook
                            ? `Webhook integration enabled. You should see a message on ${resolveWebhookService(
                                  payload.slack_incoming_webhook
                              )}.`
                            : 'Webhook integration disabled.'
                    }

                    toast.dismiss('updateCurrentTeam')
                    toast.success(
                        <div>
                            <h1>{parseUpdatedAttributeName(updatedAttribute)} updated successfully!</h1>
                            <p>{description}</p>
                        </div>,
                        {
                            toastId: 'updateCurrentTeam',
                        }
                    )

                    return patchedTeam
                },
                createTeam: async (name: string): Promise<TeamType> => await api.create('api/projects/', { name }),
                resetToken: async () => await api.update(`api/projects/${values.currentTeamId}/reset_token`, {}),
            },
        ],
    }),
    selectors: {
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
    },
    listeners: ({ actions }) => ({
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
            toast.success('Project has been deleted')
        },
        createTeamSuccess: () => {
            window.location.href = '/ingestion'
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            const appContext = getAppContext()
            const contextualTeam = appContext?.current_team
            if (contextualTeam) {
                // If app context is available (it should be practically always) we can immediately know currentTeam
                actions.loadCurrentTeamSuccess(contextualTeam)
            } else {
                // If app context is not available, a traditional request is needed
                actions.loadCurrentTeam()
            }
        },
    }),
})
