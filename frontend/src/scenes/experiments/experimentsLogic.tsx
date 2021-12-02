import { kea } from 'kea'
import { api } from 'lib/api.mock'
import { experimentsLogicType } from './experimentsLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment } from '~/types'

export const experimentsLogic = kea<experimentsLogicType>({
    path: ['scenes', 'experiments', 'experimentsLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    loaders: ({ values }) => ({
        experiments: [
            null as Experiment | null,
            {
                loadExperiments: async () => {
                    const url = `api/projects/${values.currentTeamId}/experiments`
                    return await api.get(url)
                },
            },
        ],
    }),
})
