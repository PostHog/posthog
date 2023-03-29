import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import api from 'lib/api'
import type { experimentsLogicType } from './experimentsLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { AutomationsTabs, AvailableFeature, ExperimentsTabs, ExperimentStatus } from '~/types'
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
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        // setSearchStatus: (status: ExperimentStatus | 'all') => ({ status }),
        setAutomationsTab: (tabKey: AutomationsTabs) => ({ tabKey }),
    }),
    reducers({
        searchTerm: {
            setSearchTerm: (_, { searchTerm }) => searchTerm,
        },
        // searchStatus: {
        //     setSearchStatus: (_, { status }) => status,
        // },
        tab: [
            AutomationsTabs.All as AutomationsTabs,
            {
                setAutomationsTab: (_, { tabKey }) => tabKey,
            },
        ],
    }),
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
                //     return values.experiments.filter((automation) => automation.id !== id)
                // },
                // addToExperiments: (automation: Experiment) => {
                //     return [...values.experiments, automation]
                // },
                // updateExperiments: (automation: Experiment) => {
                //     return values.experiments.map((exp) => (exp.id === automation.id ? automation : exp))
                // },
            },
        ],
    })),
    selectors(({ values }) => ({
        //     getExperimentStatus: [
        //         (s) => [s.experiments],
        //         () =>
        //             (automation: Experiment): ExperimentStatus => {
        //                 if (!automation.start_date) {
        //                     return ExperimentStatus.Draft
        //                 } else if (!automation.end_date) {
        //                     return ExperimentStatus.Running
        //                 }
        //                 return ExperimentStatus.Complete
        //             },
        //     ],
        filteredAutomations: [
            (selectors) => [
                selectors.automations,
                selectors.searchTerm,
                // selectors.searchStatus,
                selectors.tab,
                // selectors.getExperimentStatus,
            ],
            (automations, searchTerm, tab) => {
                let filteredAutomations: Automation[] = automations || []

                // if (tab === AutomationsTabs.Archived) {
                //     filteredAutomations = filteredAutomations.filter((automation) => !!automation.archived)
                // } else
                if (tab === ExperimentsTabs.Yours) {
                    filteredAutomations = filteredAutomations.filter(
                        (automation) => automation.created_by?.uuid === values.user?.uuid
                    )
                } else {
                    filteredAutomations = filteredAutomations.filter((automation) => !automation.archived)
                }

                if (searchTerm) {
                    filteredAutomations = new Fuse(filteredAutomations, {
                        keys: ['name', 'description'],
                        threshold: 0.3,
                    })
                        .search(searchTerm)
                        .map((result) => result.item)
                }

                // if (searchStatus && searchStatus !== 'all') {
                //     filteredAutomations = filteredAutomations.filter(
                //         (automation) => getExperimentStatus(automation) === searchStatus
                //     )
                // }
                return filteredAutomations
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadAutomations()
        },
    })),
])
