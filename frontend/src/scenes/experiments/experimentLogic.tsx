import { kea } from 'kea'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment } from '~/types'

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setExperiment: (experiment: Partial<Experiment>) => ({ experiment }),
        createDraftExperiment: true,
        createExperiment: true,
    },
    reducers: {
        experiment: [
            null as Experiment | null,
            {
                setExperiment: (_, { experiment }) => experiment,
            },
        ],
    },
    listeners: ({ values }) => ({
        createExperiment: async () => {
            await api.create(`api/projects/${values.currentTeamId}/experiments`, { ...values.experiment })
        },
    }),
})
