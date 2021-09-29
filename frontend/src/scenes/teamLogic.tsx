import { kea } from 'kea'
import api from 'lib/api'
import { teamLogicType } from './teamLogicType'
import { TeamType } from '~/types'
import { userLogic } from './userLogic'
import { toast } from 'react-toastify'
import React from 'react'
import { identifierToHuman, resolveWebhookService } from 'lib/utils'

export const teamLogic = kea<teamLogicType>({
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
                            <h1>
                                {updatedAttribute
                                    ? updatedAttribute === 'slack_incoming_webhook'
                                        ? 'Webhook'
                                        : identifierToHuman(updatedAttribute)
                                    : 'Project'}{' '}
                                updated successfully!
                            </h1>
                            <p>{description}</p>
                        </div>,
                        {
                            toastId: 'updateCurrentTeam',
                        }
                    )

                    return patchedTeam
                },
                createTeam: async (name: string): Promise<TeamType> => await api.create('api/projects/', { name }),
                resetToken: async () => await api.update('api/projects/@current/reset_token', {}),
            },
        ],
    }),
    selectors: ({ selectors }) => ({
        isCurrentTeamUnavailable: [
            () => [
                selectors.currentTeam,
                selectors.currentTeamLoading,
                userLogic.selectors.user,
                userLogic.selectors.userLoading,
            ],
            // If project has been loaded and is still null, it means the user just doesn't have access.
            (currentTeam, currentTeamLoading, user, userLoading): boolean =>
                !!user && !userLoading && !currentTeam && !currentTeamLoading,
        ],
    }),
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
        afterMount: [actions.loadCurrentTeam],
    }),
})
