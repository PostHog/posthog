import { kea } from 'kea'
import api from 'lib/api'
import { teamLogicType } from 'types/scenes/teamLogicType'
import { TeamType } from '~/types'
import { userLogic } from './userLogic'

export const teamLogic = kea<teamLogicType>({
    loaders: () => ({
        currentTeam: [
            null as TeamType | null,
            {
                loadCurrentTeam: () => userLogic.values.user?.team,
                createTeam: async (name: string) => await api.create('api/projects/', { name }),
            },
        ],
    }),
    listeners: {
        createTeamSuccess: () => {
            window.location.href = '/project/settings'
        },
    },
    events: ({ actions }) => ({
        afterMount: [actions.loadCurrentTeam],
    }),
})
