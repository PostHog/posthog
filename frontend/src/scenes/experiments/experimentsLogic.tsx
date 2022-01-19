import { kea } from 'kea'
import { api } from 'lib/api.mock'
import { experimentsLogicType } from './experimentsLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment, ExperimentsTabs } from '~/types'
import { CheckCircleOutlined } from '@ant-design/icons'
import { toast } from 'react-toastify'
import React from 'react'
import { toParams } from 'lib/utils'

export const experimentsLogic = kea<experimentsLogicType>({
    path: ['scenes', 'experiments', 'experimentsLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {},
    loaders: ({ values, actions }) => ({
        experiments: [
            [] as Experiment[],
            {
                loadExperiments: async (filter?: Record<string, any>) => {
                    const response = await api.get(`api/projects/${values.currentTeamId}/experiments?${filter}`)
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
            },
        ],
        tab: [
            ExperimentsTabs.All as ExperimentsTabs,
            {
                setExperimentsFilters: async ({ tab }: { tab: ExperimentsTabs }) => {
                    const tabFilter =
                        tab === ExperimentsTabs.Yours ? toParams({ user: true }) : toParams({ archived: true })
                    if (tab === ExperimentsTabs.All) {
                        actions.loadExperiments()
                    } else {
                        actions.loadExperiments(tabFilter)
                    }
                    return tab
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
