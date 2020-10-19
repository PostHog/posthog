import { kea } from 'kea'
import api from 'lib/api'
import { teamLogicType } from 'types/scenes/teamLogicType'
import { TeamType } from '~/types'

export const teamLogic = kea<teamLogicType>({
    loaders: () => ({
        currentTeam: [
            null as TeamType | null,
            {
                loadCurrentTeam: async () => await api.get('api/projects/@current'),
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
