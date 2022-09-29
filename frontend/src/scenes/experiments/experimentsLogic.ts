import { kea } from 'kea'
import api from 'lib/api'
import type { experimentsLogicType } from './experimentsLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment, ExperimentsTabs, AvailableFeature } from '~/types'
import { toParams } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'
import { lemonToast } from 'lib/components/lemonToast'

export const experimentsLogic = kea<experimentsLogicType>({
    path: ['scenes', 'experiments', 'experimentsLogic'],
    connect: { values: [teamLogic, ['currentTeamId'], userLogic, ['hasAvailableFeature']] },
    actions: {},
    loaders: ({ values, actions }) => ({
        experiments: [
            [] as Experiment[],
            {
                loadExperiments: async (filter?: string) => {
                    if (!values.hasAvailableFeature(AvailableFeature.EXPERIMENTATION)) {
                        return []
                    }
                    const response = await api.get(
                        `api/projects/${values.currentTeamId}/experiments?${filter ? filter : ''}`
                    )
                    return response.results as Experiment[]
                },
                deleteExperiment: async (id: number) => {
                    await api.delete(`api/projects/${values.currentTeamId}/experiments/${id}`)
                    lemonToast.info('Experiment removed')
                    return values.experiments.filter((experiment) => experiment.id !== id)
                },
                addToExperiments: (experiment: Experiment) => {
                    return [...values.experiments, experiment]
                },
                updateExperiments: (experiment: Experiment) => {
                    return values.experiments.map((exp) => (exp.id === experiment.id ? experiment : exp))
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
                        actions.loadExperiments(toParams({ all: true }))
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
            actions.loadExperiments(toParams({ all: true }))
        },
    }),
})
