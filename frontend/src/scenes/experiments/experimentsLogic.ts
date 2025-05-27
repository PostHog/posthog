import { LemonTagType } from '@posthog/lemon-ui'
import Fuse from 'fuse.js'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { featureFlagsLogic, type FeatureFlagsResult } from 'scenes/feature-flags/featureFlagsLogic'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { Experiment, ExperimentsTabs, ProgressStatus } from '~/types'

import type { experimentsLogicType } from './experimentsLogicType'
import { isLegacyExperiment } from './utils'

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
    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            featureFlagLogic,
            ['featureFlags'],
            featureFlagsLogic,
            ['featureFlags'],
            router,
            ['location'],
        ],
    })),
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
                // Saved Metrics is a fake tab that we use to redirect to the shared metrics page
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
        // TRICKY: we do not load all feature flags here, just the latest ones.
        unavailableFeatureFlagKeys: [
            (s) => [featureFlagsLogic.selectors.featureFlags, s.experiments],
            (featureFlags: FeatureFlagsResult, experiments: Experiment[]) => {
                return new Set([
                    ...featureFlags.results.map((flag) => flag.key),
                    ...experiments.map((experiment) => experiment.feature_flag_key),
                ])
            },
        ],
        showLegacyBadge: [
            (s) => [featureFlagsLogic.selectors.featureFlags, s.experiments],
            (featureFlags: FeatureFlagsSet, experiments: Experiment[]): boolean => {
                /**
                 * If the new query runner is enabled, we want to always show the legacy badge,
                 * even if all existing experiments are legacy experiments.
                 *
                 * Not ideal to use feature flags at this level, but this is how things are and
                 * it'll take a while to change.
                 */
                if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_NEW_QUERY_RUNNER]) {
                    return true
                }

                /**
                 * If the new query runner is not enabled, we'll set this boolean selector
                 * so the components can show the legacy badge only if there are experiments
                 * that use the NEW query runner.
                 * This covers the case when the feature was disabled after creating new experiments.
                 */
                return experiments.some((experiment) => !isLegacyExperiment(experiment))
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadExperiments()
        },
    })),
])
