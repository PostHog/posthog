import { kea } from 'kea'
import api from 'lib/api'
import { teamLogicType } from './teamLogicType'
import { TeamType, BasicTeamType } from '~/types'
import { userLogic } from './userLogic'
import { toast } from 'react-toastify'
import React from 'react'

export const teamLogic = kea<teamLogicType<TeamType, BasicTeamType>>({
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
        /*
        We use this request to load the current team object but with minimal data attributes
        so the whole app isn't frozen when loading a team with a ton of event properties.
        We store it separately to have a separate type and avoid having to do multiple checks everywhere
        to see if the full team information has been loaded.
        */
        basicCurrentTeam: [
            null as BasicTeamType | null,
            {
                loadBasicCurrentTeam: async () => {
                    try {
                        return await api.get('api/projects/@current/?basic=1')
                    } catch {
                        return null
                    }
                },
            },
        ],
        currentTeam: [
            null as TeamType | null,
            {
                loadCurrentTeam: async () => {
                    try {
                        return await api.get('api/projects/@current/')
                    } catch {
                        return null
                    }
                },
                patchCurrentTeam: async (patch: Partial<TeamType>) => {
                    if (!values.currentTeam) {
                        throw new Error('Current team has not been loaded yet, so it cannot be updated!')
                    }
                    const patchedTeam = (await api.update(`api/projects/${values.currentTeam.id}`, patch)) as TeamType
                    userLogic.actions.loadUser()
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
        patchCurrentTeamSuccess: () => {
            toast.success(
                <div>
                    <h1>Project updated successfully!</h1>
                    <p>Click here to dismiss.</p>
                </div>
            )
        },
    }),
    events: ({ actions, props }) => ({
        afterMount: () => {
            actions.loadCurrentTeam()

            if (props.basic) {
                actions.loadBasicCurrentTeam()
            }
        },
    }),
})
