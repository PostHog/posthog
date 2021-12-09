import { kea } from 'kea'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { Breadcrumb, Experiment, ExperimentResults } from '~/types'

import { experimentLogicType } from './experimentLogicType'

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setExperimentId: (experimentId: number | 'new') => ({ experimentId }),
        setNewExperimentData: (experimentData: Experiment) => ({ experimentData }),
        setExperimentResults: (experimentResults: ExperimentResults) => ({ experimentResults }),
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
        experimentResults: [
            null as ExperimentResults | null,
            {
                setExperimentResults: (_, { experimentResults }) => experimentResults,
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        createExperiment: async () => {
            await api.create(`api/projects/${values.currentTeamId}/experiments`, { ...values.newExperimentData })
        },

        loadExperiment: async () => {
            const response = await api.get(
                `api/projects/${values.currentTeamId}/experiments/${values.experimentId}/results`
            )
            console.log(response)
            actions.setExperimentResults(response)
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
                        return response as Experiment
                    }
                    return null
                },
            },
        ],
    }),
    selectors: {
        breadcrumbs: [
            (s) => [s.experimentData, s.experimentId],
            (experimentData, experimentId): Breadcrumb[] => [
                {
                    name: 'Experiments',
                    path: urls.experiments(),
                },
                {
                    name: experimentData?.name || 'New Experiment',
                    path: urls.experiment(experimentId || 'new'),
                },
            ],
        ],
    },
    urlToAction: ({ actions, values }) => ({
        '/experiments/:id': ({ id }) => {
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
