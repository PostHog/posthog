import { kea } from 'kea'
import api from 'lib/api'
import { teamLogicType } from './teamLogicType'
import { TeamType } from '~/types'
import { userLogic } from './userLogic'
import { toast } from 'react-toastify'
import React from 'react'
import { posthogEvents, identifierToHuman, resolveWebhookService } from 'lib/utils'

export interface EventProperty {
    value: string
    label: string
}

export const teamLogic = kea<teamLogicType<TeamType, EventProperty>>({
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
                                {updatedAttribute ? identifierToHuman(updatedAttribute) : 'Project'} updated
                                successfully!
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
    selectors: {
        eventProperties: [
            (s) => [s.currentTeam],
            (team): EventProperty[] =>
                team
                    ? team.event_properties.map(
                          (property: string) => ({ value: property, label: property } as EventProperty)
                      )
                    : [],
        ],
        eventPropertiesNumerical: [
            (s) => [s.currentTeam],
            (team): EventProperty[] =>
                team
                    ? team.event_properties_numerical.map(
                          (property: string) => ({ value: property, label: property } as EventProperty)
                      )
                    : [],
        ],
        eventNames: [(s) => [s.currentTeam], (team): string[] => team?.event_names ?? []],
        customEventNames: [
            (s) => [s.eventNames],
            (eventNames): string[] => {
                return eventNames.filter((event) => !event.startsWith('!'))
            },
        ],
        eventNamesGrouped: [
            (s) => [s.currentTeam],
            (team) => {
                const data = [
                    { label: 'Custom events', options: [] as EventProperty[] },
                    { label: 'PostHog events', options: [] as EventProperty[] },
                ]
                if (team) {
                    team.event_names.forEach((name: string) => {
                        const format = { label: name, value: name } as EventProperty
                        if (posthogEvents.includes(name)) {
                            return data[1].options.push(format)
                        }
                        data[0].options.push(format)
                    })
                }
                return data
            },
        ],
    },
    events: ({ actions }) => ({
        afterMount: [actions.loadCurrentTeam],
    }),
})
