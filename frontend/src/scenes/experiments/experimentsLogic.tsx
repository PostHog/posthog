import { kea } from 'kea'
import { api } from 'lib/api.mock'
import { experimentsLogicType } from './experimentsLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment } from '~/types'
import { CheckCircleOutlined } from '@ant-design/icons'
import { toast } from 'react-toastify'
import React from 'react'

export const experimentsLogic = kea<experimentsLogicType>({
    path: ['scenes', 'experiments', 'experimentsLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {},
    loaders: ({ values }) => ({
        experiments: [
            [] as Experiment[],
            {
                loadExperiments: async () => {
                    const response = await api.get(`api/projects/${values.currentTeamId}/experiments`)
                    return response.results as Experiment[]
                },
                deleteExperiment: async (id: number) => {
                    await api.delete(`api/projects/${values.currentTeamId}/experiments/${id}`)
                    toast(
                        <div>
                            <h1 className="text-success">
                                <CheckCircleOutlined /> Experiment removed
                            </h1>
                        </div>
                    )
                    return values.experiments.filter((experiment) => experiment.id !== id)
                },
                addToExperiments: (experiment: Experiment) => {
                    return [...values.experiments, experiment]
                },
                updateExperiment: (experiment: Experiment) => {
                    return values.experiments.map((exp) => (exp.id === experiment.id ? experiment : exp))
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadExperiments()
        },
    }),
})
