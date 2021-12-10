import { kea } from 'kea'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment } from '~/types'

import { experimentLogicType } from './experimentLogicType'

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setExperimentId: (experimentId: number | 'new') => ({ experimentId }),
        setNewExperimentData: (experimentData: Experiment) => ({ experimentData }),
        createDraftExperiment: true,
        createExperiment: true,
    },
    reducers: {
        experimentId: [
            null as number | 'new' | null,
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
                    if (values.experimentId && values.experimentId !== 'new') {
                        const response = await api.get(
                            `api/projects/${values.currentTeamId}/experiments/${values.experimentId}`
                        )
                        console.log(response)
                        return response as Experiment
                    }
                    return null
                },
            },
        ],
    }),
    urlToAction: ({ actions, values }) => ({
        '/experiments/:id': ({ id }) => {
            console.log('exp id: ', id)
            if (id) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                // TODO: optimise loading if already loaded Experiment
                // like in featureFlagLogic.tsx
                if (parsedId !== values.experimentId) {
                    actions.setExperimentId(parsedId)
                }

                if (parsedId !== 'new') {
                    actions.loadExperiment()
                }
            }
        },
    }),
})
