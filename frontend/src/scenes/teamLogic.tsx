import { kea } from 'kea'
import api from 'lib/api'
import { teamLogicType } from './teamLogicType'
import { TeamType } from '~/types'

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
            window.location.href = '/project/settings'
        },
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadCurrentTeam],
    }),
})
