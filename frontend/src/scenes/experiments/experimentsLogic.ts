import { LemonTagType } from '@posthog/lemon-ui'
import Fuse from 'fuse.js'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { Experiment, ExperimentsTabs, ProgressStatus } from '~/types'

import type { experimentsLogicType } from './experimentsLogicType'

export function getExperimentStatus(experiment: Experiment): ProgressStatus {
    if (!experiment.start_date) {
        return ProgressStatus.Draft
    } else if (!experiment.end_date) {
        return ProgressStatus.Running
    }
    return ProgressStatus.Complete
}

export function getExperimentStatusColor(status: ProgressStatus): LemonTagType {
    switch (status) {
        case ProgressStatus.Draft:
            return 'default'
        case ProgressStatus.Running:
            return 'success'
        case ProgressStatus.Complete:
            return 'completion'
    }
}

export const experimentsLogic = kea<experimentsLogicType>([
    path(['scenes', 'experiments', 'experimentsLogic']),
    connect({
        values: [
            projectLogic,
            ['currentProjectId'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            featureFlagLogic,
            ['featureFlags'],
            router,
            ['location'],
        ],
    }),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSearchStatus: (status: ProgressStatus | 'all') => ({ status }),
        setExperimentsTab: (tabKey: ExperimentsTabs) => ({ tabKey }),
        setUserFilter: (userFilter: string | null) => ({ userFilter }),
    }),
    reducers({
        searchTerm: {
            setSearchTerm: (_, { searchTerm }) => searchTerm,
        },
        searchStatus: {
            setSearchStatus: (_, { status }) => status,
        },
        userFilter: [
            null as string | null,
            {
                setUserFilter: (_, { userFilter }) => userFilter,
            },
        ],
        tab: [
            ExperimentsTabs.All as ExperimentsTabs,
            {
                setExperimentsTab: (state, { tabKey }) => tabKey ?? state,
            },
        ],
    }),
    listeners(({ actions }) => ({
        setExperimentsTab: ({ tabKey }) => {
            if (tabKey === ExperimentsTabs.SharedMetrics) {
                // Saved Metrics is a fake tab that we use to redirect to the saved metrics page
                actions.setExperimentsTab(ExperimentsTabs.All)
                router.actions.push('/experiments/shared-metrics')
            } else {
                router.actions.push('/experiments')
            }
        },
    })),
    loaders(({ values }) => ({
        experiments: [
            [] as Experiment[],
            {
                loadExperiments: async () => {
                    const response = await api.get(`api/projects/${values.currentProjectId}/experiments?limit=1000`)
                    return response.results as Experiment[]
                },
                deleteExperiment: async (id: number) => {
                    await api.delete(`api/projects/${values.currentProjectId}/experiments/${id}`)
                    lemonToast.info('Experiment removed')
                    return values.experiments.filter((experiment) => experiment.id !== id)
                },
                archiveExperiment: async (id: number) => {
                    await api.update(`api/projects/${values.currentProjectId}/experiments/${id}`, { archived: true })
                    lemonToast.info('Experiment archived')
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
    })),
    selectors(({ values }) => ({
        filteredExperiments: [
            (s) => [s.experiments, s.searchTerm, s.searchStatus, s.userFilter, s.tab],
            (experiments, searchTerm, searchStatus, userFilter, tab) => {
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

                if (userFilter) {
                    filteredExperiments = filteredExperiments.filter(
                        (experiment) => experiment.created_by?.uuid === userFilter
                    )
                }
                return filteredExperiments
            },
        ],
        shouldShowEmptyState: [
            (s) => [s.experimentsLoading, s.experiments],
            (experimentsLoading, experiments): boolean => {
                return experiments.length === 0 && !experimentsLoading && !values.searchTerm && !values.searchStatus
            },
        ],
        webExperimentsAvailable: [
            () => [featureFlagLogic.selectors.featureFlags],
            (featureFlags: FeatureFlagsSet) => featureFlags[FEATURE_FLAGS.WEB_EXPERIMENTS],
        ],
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadExperiments()
        },
    })),
])
