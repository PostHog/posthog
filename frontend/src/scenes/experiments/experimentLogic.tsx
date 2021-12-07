import { kea } from 'kea'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment } from '~/types'

import { experimentLogicType } from './experimentLogicType'
export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setExperiment: (experiment: Experiment) => ({ experiment }),
        createExperiment: (draft?: boolean) => ({ draft }),
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
        createExperiment: async (draft?: boolean) => {
            console.log('draft', draft)
            await api.create(`api/projects/${values.currentTeamId}/experiments`, {
                ...values.experiment,
                ...(draft && { start_date: dayjs() }),
            })
        },
    }),
})
