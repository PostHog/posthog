import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import api from 'lib/api'
import type { experimentsLogicType } from './experimentsLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { AvailableFeature, ExperimentsTabs, ExperimentStatus } from '~/types'
import { Automation } from './schema'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import Fuse from 'fuse.js'
import { userLogic } from 'scenes/userLogic'
import { subscriptions } from 'kea-subscriptions'
import { loaders } from 'kea-loaders'

import type { automationsLogicType } from './automationsLogicType'

export const automationsLogic = kea<automationsLogicType>([
    path(['scenes', 'automations', 'automationsLogic']),
    connect({ values: [teamLogic, ['currentTeamId'], userLogic, ['user', 'hasAvailableFeature']] }),
    // actions({
    //     setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    //     setSearchStatus: (status: ExperimentStatus | 'all') => ({ status }),
    //     setExperimentsTab: (tabKey: ExperimentsTabs) => ({ tabKey }),
    // }),
    // reducers({
    //     searchTerm: {
    //         setSearchTerm: (_, { searchTerm }) => searchTerm,
    //     },
    //     searchStatus: {
    //         setSearchStatus: (_, { status }) => status,
    //     },
    //     tab: [
    //         ExperimentsTabs.All as ExperimentsTabs,
    //         {
    //             setExperimentsTab: (_, { tabKey }) => tabKey,
    //         },
    //     ],
    // }),
    loaders(({ values }) => ({
        automations: [
            [] as Automation[],
            {
                loadAutomations: async () => {
                    // if (!values.hasAutomationAvailableFeature) {
                    //     return []
                    // }
                    const response = await api.get(`api/projects/${values.currentTeamId}/automations`)
                    return response.results as Automation[]
                },
                // deleteExperiment: async (id: number) => {
                //     await api.delete(`api/projects/${values.currentTeamId}/experiments/${id}`)
                //     lemonToast.info('Experiment removed')
                //     return values.experiments.filter((experiment) => experiment.id !== id)
                // },
                // addToExperiments: (experiment: Experiment) => {
                //     return [...values.experiments, experiment]
                // },
                // updateExperiments: (experiment: Experiment) => {
                //     return values.experiments.map((exp) => (exp.id === experiment.id ? experiment : exp))
                // },
            },
        ],
    })),
    // selectors(({ values }) => ({
    //     getExperimentStatus: [
    //         (s) => [s.experiments],
    //         () =>
    //             (experiment: Experiment): ExperimentStatus => {
    //                 if (!experiment.start_date) {
    //                     return ExperimentStatus.Draft
    //                 } else if (!experiment.end_date) {
    //                     return ExperimentStatus.Running
    //                 }
    //                 return ExperimentStatus.Complete
    //             },
    //     ],
    //     filteredExperiments: [
    //         (selectors) => [
    //             selectors.experiments,
    //             selectors.searchTerm,
    //             selectors.searchStatus,
    //             selectors.tab,
    //             selectors.getExperimentStatus,
    //         ],
    //         (experiments, searchTerm, searchStatus, tab, getExperimentStatus) => {
    //             let filteredExperiments: Experiment[] = experiments

    //             if (tab === ExperimentsTabs.Archived) {
    //                 filteredExperiments = filteredExperiments.filter((experiment) => !!experiment.archived)
    //             } else if (tab === ExperimentsTabs.Yours) {
    //                 filteredExperiments = filteredExperiments.filter(
    //                     (experiment) => experiment.created_by?.uuid === values.user?.uuid
    //                 )
    //             } else {
    //                 filteredExperiments = filteredExperiments.filter((experiment) => !experiment.archived)
    //             }

    //             if (searchTerm) {
    //                 filteredExperiments = new Fuse(filteredExperiments, {
    //                     keys: ['name', 'feature_flag_key', 'description'],
    //                     threshold: 0.3,
    //                 })
    //                     .search(searchTerm)
    //                     .map((result) => result.item)
    //             }

    //             if (searchStatus && searchStatus !== 'all') {
    //                 filteredExperiments = filteredExperiments.filter(
    //                     (experiment) => getExperimentStatus(experiment) === searchStatus
    //                 )
    //             }
    //             return filteredExperiments
    //         },
    //     ],
    // })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadAutomations()
        },
    })),
])
