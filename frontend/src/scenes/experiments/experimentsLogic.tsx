import { kea } from 'kea'
import { combineUrl, router } from 'kea-router'
import { api } from 'lib/api.mock'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { Experiment } from '~/types'

export const experimentsLogic = kea<experimentsLogicType>({
    path: ['scenes', 'experiments', 'experimentsLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setOpenExperiment: (experiment) => ({ experiment }),
    },
    loaders: ({ values }) => ({
        experiments: [
            null as Experiment | null,
            {
                loadExperiments: async () => {
                    const url = `api/projects/${values.currentTeamId}/experiments`
                    return await api.get(url)
                },
            },
        ],
    }),
    reducers: {
        openExperiment: [
            null,
            {
                setOpenExperiment: (_, { experiment }) => experiment,
            },
        ],
    },
    actionToUrl: ({ values }) => ({
        setOpenExperiment: () =>
            combineUrl(
                values.openExperiment ? urls.experiment(values.openExperiment.id || 'new') : urls.experiments(),
                router.values.searchParams
            ).url,
    }),
})
