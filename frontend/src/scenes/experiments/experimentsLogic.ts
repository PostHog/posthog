import { LemonTagType } from '@posthog/lemon-ui'
import { PaginationManual } from '@posthog/lemon-ui'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api, { CountedPaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { objectsEqual, toParams } from 'lib/utils'
import { featureFlagsLogic, type FeatureFlagsResult } from 'scenes/feature-flags/featureFlagsLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Experiment, ExperimentsTabs, ProgressStatus } from '~/types'

import type { experimentsLogicType } from './experimentsLogicType'

export const EXPERIMENTS_PER_PAGE = 100

export interface ExperimentsResult extends CountedPaginatedResponse<Experiment> {
    /* not in the API response */
    filters?: ExperimentsFilters | null
}

export interface ExperimentsFilters {
    search?: string
    status?: ProgressStatus | 'all'
    created_by_id?: number
    page?: number
    order?: string
}

const DEFAULT_FILTERS: ExperimentsFilters = {
    search: undefined,
    status: 'all',
    created_by_id: undefined,
    page: 1,
}

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
        setExperimentsTab: (tabKey: ExperimentsTabs) => ({ tabKey }),
        setExperimentsFilters: (filters: Partial<ExperimentsFilters>, replace?: boolean) => ({ filters, replace }),
    }),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setExperimentsFilters: (state, { filters, replace }) => {
                    if (replace) {
                        return { ...filters }
                    }
                    return { ...state, ...filters }
                },
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
        setExperimentsFilters: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadExperiments()
        },
        setExperimentsTab: ({ tabKey }) => {
            if (tabKey === ExperimentsTabs.SharedMetrics) {
                // Saved Metrics is a fake tab that we use to redirect to the shared metrics page
                actions.setExperimentsTab(ExperimentsTabs.All)
                router.actions.push('/experiments/shared-metrics')
            }
        },
    })),
    loaders(({ values }) => ({
        experiments: [
            { results: [], count: 0, filters: DEFAULT_FILTERS, offset: 0 } as ExperimentsResult,
            {
                loadExperiments: async () => {
                    const response = await api.get(
                        `api/projects/${values.currentProjectId}/experiments?${toParams(values.paramsFromFilters)}`
                    )
                    return {
                        ...response,
                        offset: values.paramsFromFilters.offset,
                    }
                },
                archiveExperiment: async (id: number) => {
                    await api.update(`api/projects/${values.currentProjectId}/experiments/${id}`, { archived: true })
                    lemonToast.info('Experiment archived')
                    return {
                        ...values.experiments,
                        results: values.experiments.results.filter((experiment) => experiment.id !== id),
                        count: values.experiments.count - 1,
                    }
                },
                addToExperiments: (experiment: Experiment) => {
                    return {
                        ...values.experiments,
                        results: [...values.experiments.results, experiment],
                        count: values.experiments.count + 1,
                    }
                },
                updateExperiments: (experiment: Experiment) => {
                    return {
                        ...values.experiments,
                        results: values.experiments.results.map((exp) => (exp.id === experiment.id ? experiment : exp)),
                        count: values.experiments.count,
                    }
                },
            },
        ],
    })),
    selectors(() => ({
        count: [(selectors) => [selectors.experiments], (experiments) => experiments.count],
        paramsFromFilters: [
            (s) => [s.filters, s.tab],
            (filters: ExperimentsFilters, tab: ExperimentsTabs) => ({
                ...filters,
                limit: EXPERIMENTS_PER_PAGE,
                offset: filters.page ? (filters.page - 1) * EXPERIMENTS_PER_PAGE : 0,
                archived: tab === ExperimentsTabs.Archived,
            }),
        ],
        shouldShowEmptyState: [
            (s) => [s.experimentsLoading, s.experiments, s.filters],
            (experimentsLoading, experiments, filters): boolean => {
                return !experimentsLoading && experiments.results.length <= 0 && objectsEqual(filters, DEFAULT_FILTERS)
            },
        ],
        pagination: [
            (s) => [s.filters, s.count],
            (filters, count): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: EXPERIMENTS_PER_PAGE,
                    currentPage: filters.page || 1,
                    entryCount: count,
                }
            },
        ],
        webExperimentsAvailable: [
            () => [featureFlagLogic.selectors.featureFlags],
            (featureFlags: FeatureFlagsSet) => featureFlags[FEATURE_FLAGS.WEB_EXPERIMENTS],
        ],
        // TRICKY: we do not load all feature flags here, just the latest ones.
        unavailableFeatureFlagKeys: [
            (s) => [featureFlagsLogic.selectors.featureFlags, s.experiments],
            (featureFlags: FeatureFlagsResult, experiments: ExperimentsResult) => {
                return new Set([
                    ...featureFlags.results.map((flag) => flag.key),
                    ...experiments.results.map((experiment) => experiment.feature_flag_key),
                ])
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadExperiments()
        },
    })),
    actionToUrl(({ values }) => {
        const changeUrl = ():
            | [
                  string,
                  Record<string, any>,
                  Record<string, any>,
                  {
                      replace: boolean
                  }
              ]
            | void => {
            const searchParams: Record<string, string | number> = {
                ...values.filters,
            }

            if (values.tab !== ExperimentsTabs.All) {
                searchParams['tab'] = values.tab
            }

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: false }]
        }

        return {
            setExperimentsFilters: changeUrl,
            setExperimentsTab: changeUrl,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.experiments()]: async (_, searchParams) => {
            const tabInURL = searchParams['tab']

            if (!tabInURL) {
                if (values.tab !== ExperimentsTabs.All) {
                    actions.setExperimentsTab(ExperimentsTabs.All)
                }
            } else if (tabInURL !== values.tab) {
                actions.setExperimentsTab(tabInURL)
            }

            const { page, search, status, created_by_id, order } = searchParams
            const pageFiltersFromUrl: Partial<ExperimentsFilters> = {
                search,
                created_by_id,
                order,
            }

            pageFiltersFromUrl.status = status || 'all'
            pageFiltersFromUrl.page = page !== undefined ? parseInt(page) : 1

            actions.setExperimentsFilters({ ...DEFAULT_FILTERS, ...pageFiltersFromUrl })
        },
    })),
])
