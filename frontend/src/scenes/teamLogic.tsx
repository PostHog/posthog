import { kea } from 'kea'
import api from 'lib/api'
import { teamLogicType } from './teamLogicType'
import { TeamType } from '~/types'
import { userLogic } from './userLogic'

export const teamLogic = kea<teamLogicType<TeamType>>({
    actions: {
        deleteCurrentTeam: true,
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
                // no API request in patch as that's handled in userLogic for now
                patchCurrentTeam: (patch: Partial<TeamType>) =>
                    values.currentTeam ? { ...values.currentTeam, ...patch } : null,
                createTeam: async (name: string) => await api.create('api/projects/', { name }),
                resetToken: async () => await api.update('api/projects/@current/reset_token', {}),
            },
        ],
    }),
    listeners: ({ values }) => ({
        deleteCurrentTeam: async () => {
            if (values.currentTeam) {
                api.delete(`api/projects/${values.currentTeam.id}`)
            }
        },
        createTeamSuccess: () => {
            let location = '/ingestion'
            if (userLogic.values.user?.organization?.teams) {
                for (const team of userLogic.values.user.organization.teams) {
                    if (!team.is_demo && team.id !== values.currentTeam?.id) {
                        /* If organization already has another non-demo project setup, take to settings, otherwise take to
                        ingestion wizard */
                        location = '/project/settings'
                    }
                }
            }
            window.location.href = location
        },
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadCurrentTeam],
    }),
})
