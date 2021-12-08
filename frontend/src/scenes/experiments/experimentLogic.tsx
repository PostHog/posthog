import { kea } from 'kea'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment } from '~/types'

import { experimentLogicType } from './experimentLogicType'
import { experimentsLogic } from './experimentsLogic'

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setExperimentId: (experimentId: string) => ({ experimentId }),
        setNewExperimentData: (experimentData: Experiment) => ({ experimentData }),
        createDraftExperiment: true,
        createExperiment: true,
    },
    reducers: {
        experimentId: [
            null as string | null,
            {
                setExperimentId: (_, { experimentId }) => experimentId,
            },
        ],
        newExperimentData: [
            null as Experiment | null,
            {
                setNewExperimentData: (_, { experimentData }) => experimentData,
            },
        ],
    },
    listeners: ({ values }) => ({
        createExperiment: async () => {
            await api.create(`api/projects/${values.currentTeamId}/experiments`, { ...values.newExperimentData })
        },
    }),
    loaders: ({ values }) => ({
        experimentData: [
            null as Experiment | null,
            {
                loadExperiment: async () => {
                    const { data } = await api.get(
                        `api/projects/${values.currentTeamId}/experiments/${values.experimentId}`
                    )
                    console.log(data)
                    return data
                },
            },
        ],
    }),
    urlToAction: ({ actions, values }) => ({
        '/experiments/:id': ({ id }) => {
            console.log('exp id: ', id)
            if (id && id !== values.experimentData?.id) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                actions.setExperimentId(id)

                const foundExperiment = experimentsLogic
                    .findMounted()
                    ?.values.experiments.find((experiment) => experiment.id === parsedId)
                if (foundExperiment) {
                    actions.setExperimentId(id)
                } else {
                    actions.setExperimentId('new')
                }

                if (id !== 'new') {
                    actions.loadExperiment()
                }
            }
        },
    }),
})
