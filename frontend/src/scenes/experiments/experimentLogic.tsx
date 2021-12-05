import { kea } from 'kea'
import { Experiment } from '~/types'

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    actions: {
        setExperiment: (experiment: Partial<Experiment>) => ({ experiment }),
    },
    reducers: {
        experiment: [
            null as Experiment | null,
            {
                setExperiment: (_, { experiment }) => experiment,
            },
        ],
    },
})
