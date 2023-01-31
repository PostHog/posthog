import { kea } from 'kea'
import api from 'lib/api'
import type { experimentsLogicType } from './experimentsLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment, ExperimentsTabs, AvailableFeature, ExperimentStatus } from '~/types'
import { userLogic } from 'scenes/userLogic'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import Fuse from 'fuse.js'

export const experimentsLogic = kea<experimentsLogicType>({
    path: ['scenes', 'experiments', 'experimentsLogic'],
    connect: { values: [teamLogic, ['currentTeamId'], userLogic, ['hasAvailableFeature', 'user']] },
    actions: {
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSearchStatus: (status: ExperimentStatus | 'all') => ({ status }),
        setExperimentsTab: (tabKey: ExperimentsTabs) => ({ tabKey }),
    },
    reducers: {
        searchTerm: {
            setSearchTerm: (_, { searchTerm }) => searchTerm,
        },
        searchStatus: {
            setSearchStatus: (_, { status }) => status,
        },
        tab: [
            ExperimentsTabs.All as ExperimentsTabs,
            {
                setExperimentsTab: (_, { tabKey }) => tabKey,
            },
        ],
    },
    loaders: ({ values }) => ({
        experiments: [
            [] as Experiment[],
            {
                loadExperiments: async () => {
                    if (!values.hasAvailableFeature(AvailableFeature.EXPERIMENTATION)) {
                        return []
                    }
                    const response = await api.get(`api/projects/${values.currentTeamId}/experiments`)
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
    }),
    selectors: ({ values }) => ({
        getExperimentStatus: [
            (s) => [s.experiments],
            () =>
                (experiment: Experiment): ExperimentStatus => {
                    if (!experiment.start_date) {
                        return ExperimentStatus.Draft
                    } else if (!experiment.end_date) {
                        return ExperimentStatus.Running
                    }
                    return ExperimentStatus.Complete
                },
        ],
        filteredExperiments: [
            (selectors) => [
                selectors.experiments,
                selectors.searchTerm,
                selectors.searchStatus,
                selectors.tab,
                selectors.getExperimentStatus,
            ],
            (experiments, searchTerm, searchStatus, tab, getExperimentStatus) => {
                let filteredExperiments: Experiment[] = experiments

                if (tab === ExperimentsTabs.Archived) {
                    filteredExperiments = filteredExperiments.filter((experiment) => !!experiment.archived)
                } else if (tab === ExperimentsTabs.Yours) {
                    filteredExperiments = filteredExperiments.filter(
                        (experiment) => experiment.created_by?.uuid === values.user?.uuid
                    )
                } else {
                    filteredExperiments = filteredExperiments.filter((experiment) => !experiment.archived)
                }

                if (searchTerm) {
                    filteredExperiments = new Fuse(filteredExperiments, {
                        keys: ['name', 'feature_flag_key', 'description'],
                        threshold: 0.3,
                    })
                        .search(searchTerm)
                        .map((result) => result.item)
                }

                if (searchStatus && searchStatus !== 'all') {
                    filteredExperiments = filteredExperiments.filter(
                        (experiment) => getExperimentStatus(experiment) === searchStatus
                    )
                }
                return filteredExperiments
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadExperiments()
        },
    }),
})
