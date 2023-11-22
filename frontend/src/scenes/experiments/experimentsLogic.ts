import { LemonTagType } from '@posthog/lemon-ui'
import Fuse from 'fuse.js'
import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, Experiment, ExperimentsTabs, ProductKey, ProgressStatus } from '~/types'

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
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    }),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSearchStatus: (status: ProgressStatus | 'all') => ({ status }),
        setExperimentsTab: (tabKey: ExperimentsTabs) => ({ tabKey }),
    }),
    reducers({
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
    }),
    loaders(({ values }) => ({
        experiments: [
            [] as Experiment[],
            {
                loadExperiments: async () => {
                    if (!values.hasExperimentAvailableFeature) {
                        return []
                    }
                    const response = await api.get(`api/projects/${values.currentTeamId}/experiments?limit=1000`)
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
    })),
    selectors(({ values }) => ({
        filteredExperiments: [
            (selectors) => [selectors.experiments, selectors.searchTerm, selectors.searchStatus, selectors.tab],
            (experiments, searchTerm, searchStatus, tab) => {
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
        hasExperimentAvailableFeature: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.EXPERIMENTATION),
        ],
        shouldShowEmptyState: [
            (s) => [s.experimentsLoading, s.filteredExperiments],
            (experimentsLoading, filteredExperiments): boolean => {
                return (
                    filteredExperiments.length === 0 &&
                    !experimentsLoading &&
                    !values.searchTerm &&
                    !values.searchStatus
                )
            },
        ],
        shouldShowProductIntroduction: [
            (s) => [s.user, s.featureFlags],
            (user, featureFlags): boolean => {
                return (
                    !user?.has_seen_product_intro_for?.[ProductKey.EXPERIMENTS] &&
                    !!featureFlags[FEATURE_FLAGS.SHOW_PRODUCT_INTRO_EXISTING_PRODUCTS]
                )
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadExperiments()
        },
    })),
    subscriptions(({ actions }) => ({
        hasExperimentAvailableFeature: (hasExperimentAvailableFeature, prevValue) => {
            if (hasExperimentAvailableFeature && prevValue === false) {
                actions.loadExperiments()
            }
        },
    })),
])
