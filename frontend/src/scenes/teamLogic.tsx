import { kea } from 'kea'
import api from 'lib/api'
import { teamLogicType } from './teamLogicType'
import { TeamType } from '~/types'
import { toast } from 'react-toastify'
import React from 'react'
import { posthogEvents, capitalizeFirstLetter } from 'lib/utils'

export interface EventProperty {
    value: string
    label: string
}

export const teamLogic = kea<teamLogicType<TeamType, EventProperty>>({
    actions: {
        deleteTeam: (team: TeamType) => ({ team }),
        deleteTeamSuccess: true,
        deleteTeamFailure: true,
        // updateController can be used to handle special logic when updating a team for a particular instance (e.g. showing a different success message)
        updateCurrentTeamSuccess: (currentTeam: TeamType, updateController?: string, updatedAttribute?: string) => ({
            currentTeam,
            updateController,
            updatedAttribute,
        }),
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
        currentTeam: [
            null as TeamType | null,
            {
                updateCurrentTeamSuccess: (_, { currentTeam }) => {
                    console.log('reducer', currentTeam)
                    return currentTeam
                },
            },
        ],
    },
    loaders: ({ values, actions }) => ({
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
                updateCurrentTeam: async ({
                    payload,
                    updateController,
                }: {
                    payload: Partial<TeamType>
                    updateController?: string
                }) => {
                    if (!values.currentTeam) {
                        throw new Error('Current team has not been loaded yet, so it cannot be updated!')
                    }
                    const updatedAttribute = Object.keys(payload).length === 1 ? Object.keys(payload)[0] : undefined
                    const patchedTeam = (await api.update(`api/projects/${values.currentTeam.id}`, payload)) as TeamType
                    console.log(patchedTeam)
                    actions.updateCurrentTeamSuccess(patchedTeam, updateController, updatedAttribute)

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
        updateCurrentTeamSuccess: ({ updateController, updatedAttribute }) => {
            console.log(updateController, updatedAttribute, 'listener')
            if (!updateController) {
                /* By default we show a success message. If `updateController` is set, we let the listening
                controller handle this logic. */
                toast.success(
                    <div>
                        <h1>
                            {updatedAttribute ? capitalizeFirstLetter(updatedAttribute) : 'Project'} updated
                            successfully!
                        </h1>
                        <p>Your project's settings have been successfully updated. Click here to dismiss.</p>
                    </div>
                )
            }
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
