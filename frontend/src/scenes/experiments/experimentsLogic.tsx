import { kea } from 'kea'
import { combineUrl, router } from 'kea-router'
import { api } from 'lib/api.mock'
import { experimentsLogicType } from './experimentsLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { Experiment } from '~/types'

export const experimentsLogic = kea<experimentsLogicType>({
    path: ['scenes', 'experiments', 'experimentsLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setOpenExperiment: (experiment: Experiment) => ({ experiment }),
    },
    loaders: ({ values }) => ({
        experiments: [
            [] as Experiment[],
            {
                loadExperiments: async () => {
                    const response = await api.get(`api/projects/${values.currentTeamId}/experiments`)
                    console.log(response)
                    return response.results as Experiment
                },
            },
        ],
    }),
    reducers: {
        openExperiment: [
            null as Experiment | null,
            {
                setOpenExperiment: (_, { experiment }) => experiment,
            },
        ],
    },
    actionToUrl: ({ values }) => ({
        setOpenExperiment: () =>
            combineUrl(values.openExperiment ? urls.experiment('new') : urls.experiments(), router.values.searchParams)
                .url,
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadExperiments()
        },
    }),
})
