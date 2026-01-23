import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { LemonTagType, PaginationManual } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual, toParams } from 'lib/utils'
import { FLAGS_PER_PAGE, type FeatureFlagsResult, featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import {
    ActivityScope,
    Breadcrumb,
    Experiment,
    ExperimentProgressStatus,
    ExperimentVelocityStats,
    ExperimentsTabs,
    FeatureFlagType,
} from '~/types'

import type { experimentsLogicType } from './experimentsLogicType'

export const EXPERIMENTS_PER_PAGE = 100

export interface ExperimentsResult extends CountedPaginatedResponse<Experiment> {
    /* not in the API response */
    filters?: ExperimentsFilters | null
}

export interface ExperimentsFilters {
    search?: string
    status?: ExperimentProgressStatus | 'all'
    created_by_id?: number
    archived?: boolean
    page?: number
    order?: string
}

export interface FeatureFlagModalFilters {
    active?: string
    created_by_id?: number
    search?: string
    order?: string
    page?: number
    evaluation_runtime?: string
}

const DEFAULT_FILTERS: ExperimentsFilters = {
    search: undefined,
    status: 'all',
    created_by_id: undefined,
    archived: false,
    page: 1,
    order: undefined,
}

const DEFAULT_MODAL_FILTERS: FeatureFlagModalFilters = {
    active: undefined,
    created_by_id: undefined,
    search: undefined,
    order: undefined,
    page: 1,
    evaluation_runtime: undefined,
}

export function getExperimentStatus(experiment: Experiment): ExperimentProgressStatus {
    if (!experiment.start_date) {
        return ExperimentProgressStatus.Draft
    } else if (!experiment.end_date) {
        // When the feature flag is disabled, we show "Paused" to the user for better UX.
        // This is just a virtual status, the backend still considers the experiment "running".
        if (experiment.feature_flag && !experiment.feature_flag.active) {
            return ExperimentProgressStatus.Paused
        }
        return ExperimentProgressStatus.Running
    }
    return ExperimentProgressStatus.Complete
}

export function isSingleVariantShipped(experiment: Experiment): boolean {
    const filters = experiment.feature_flag?.filters

    return (
        !!filters &&
        Array.isArray(filters.groups?.[0]?.properties) &&
        filters.groups?.[0]?.properties?.length === 0 &&
        filters.groups?.[0]?.rollout_percentage === 100 &&
        (filters.multivariate?.variants?.some(({ rollout_percentage }) => rollout_percentage === 100) || false)
    )
}

export function getShippedVariantKey(experiment: Experiment): string | null {
    if (!isSingleVariantShipped(experiment)) {
        return null
    }
    return (
        experiment.feature_flag?.filters.multivariate?.variants?.find(
            ({ rollout_percentage }) => rollout_percentage === 100
        )?.key || null
    )
}

export function getExperimentStatusColor(status: ExperimentProgressStatus): LemonTagType {
    switch (status) {
        case ExperimentProgressStatus.Draft:
            return 'default'
        case ExperimentProgressStatus.Running:
            return 'success'
        case ExperimentProgressStatus.Paused:
            return 'warning'
        case ExperimentProgressStatus.Complete:
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
            teamLogic,
            ['currentTeam'],
        ],
        actions: [teamLogic, ['loadCurrentTeamSuccess', 'updateCurrentTeamSuccess']],
    })),
    actions({
        setExperimentsTab: (tabKey: ExperimentsTabs) => ({ tabKey }),
        setExperimentsFilters: (filters: Partial<ExperimentsFilters>, replace?: boolean) => ({ filters, replace }),
        setFeatureFlagModalFilters: (filters: Partial<FeatureFlagModalFilters>, replace?: boolean) => ({
            filters,
            replace,
        }),
        resetFeatureFlagModalFilters: true,
        openFeatureFlagModal: true,
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
        featureFlagModalFilters: [
            DEFAULT_MODAL_FILTERS,
            {
                setFeatureFlagModalFilters: (state, { filters, replace }) => {
                    if (replace) {
                        return { ...filters }
                    }
                    return { ...state, ...filters }
                },
                resetFeatureFlagModalFilters: () => DEFAULT_MODAL_FILTERS,
            },
        ],
        tab: [
            ExperimentsTabs.All as ExperimentsTabs,
            {
                setExperimentsTab: (state, { tabKey }) => tabKey ?? state,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setExperimentsFilters: async (_, breakpoint) => {
            /**
             * this debounces the search input. Yeah, I know.
             */
            await breakpoint(300)
            actions.loadExperiments()
        },
        setFeatureFlagModalFilters: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadFeatureFlagModalFeatureFlags()
        },
        resetFeatureFlagModalFilters: () => {
            actions.loadFeatureFlagModalFeatureFlags()
        },
        openFeatureFlagModal: () => {
            actions.loadFeatureFlagModalFeatureFlags()
        },
        loadCurrentTeamSuccess: () => {
            if (values.featureFlagModalFeatureFlags.results.length > 0) {
                actions.loadFeatureFlagModalFeatureFlags()
            }
        },
        updateCurrentTeamSuccess: () => {
            if (values.featureFlagModalFeatureFlags.results.length > 0) {
                actions.loadFeatureFlagModalFeatureFlags()
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
                duplicateExperiment: async (payload: { id: number; featureFlagKey?: string }) => {
                    const data = payload.featureFlagKey ? { feature_flag_key: payload.featureFlagKey } : {}
                    const duplicatedExperiment = await api.create(
                        `api/projects/${values.currentProjectId}/experiments/${payload.id}/duplicate`,
                        data
                    )
                    lemonToast.success('Experiment duplicated successfully')
                    // Navigate to the newly created experiment
                    router.actions.push(urls.experiment(duplicatedExperiment.id))

                    return {
                        ...values.experiments,
                        results: [duplicatedExperiment, ...values.experiments.results],
                        count: values.experiments.count + 1,
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
        featureFlagModalFeatureFlags: [
            { results: [], count: 0 } as { results: FeatureFlagType[]; count: number },
            {
                loadFeatureFlagModalFeatureFlags: async () => {
                    const response = await api.get(
                        `api/projects/${values.currentProjectId}/experiments/eligible_feature_flags/?${toParams({
                            ...values.featureFlagModalParamsFromFilters,
                        })}`
                    )
                    return response
                },
            },
        ],
        experimentsStats: [
            {
                launched_last_30d: 0,
                launched_previous_30d: 0,
                percent_change: 0,
                active_experiments: 0,
                completed_last_30d: 0,
            } as ExperimentVelocityStats,
            {
                loadExperimentsStats: async () => {
                    const response = await api.get(`api/projects/${values.currentProjectId}/experiments/stats/`)
                    return response
                },
            },
        ],
    })),
    selectors(() => ({
        count: [(selectors) => [selectors.experiments], (experiments) => experiments.count],
        paramsFromFilters: [
            (s) => [s.filters],
            (filters: ExperimentsFilters) => ({
                ...filters,
                limit: EXPERIMENTS_PER_PAGE,
                offset: filters.page ? (filters.page - 1) * EXPERIMENTS_PER_PAGE : 0,
            }),
        ],
        featureFlagModalParamsFromFilters: [
            (s) => [s.featureFlagModalFilters, s.currentTeam],
            (filters: FeatureFlagModalFilters, currentTeam) => {
                const params: Record<string, any> = {
                    ...filters,
                    limit: FLAGS_PER_PAGE,
                    offset: filters.page ? (filters.page - 1) * FLAGS_PER_PAGE : 0,
                }

                // Add evaluation tags filter if required by team
                if (currentTeam?.require_evaluation_contexts) {
                    params.has_evaluation_tags = true
                }

                return params
            },
        ],
        featureFlagModalPageFromURL: [
            () => [router.selectors.searchParams],
            (searchParams) => {
                return parseInt(searchParams['ff_page']) || 1
            },
        ],
        featureFlagModalPagination: [
            (s) => [s.featureFlagModalFilters, s.featureFlagModalFeatureFlags, s.featureFlagModalPageFromURL],
            (filters, featureFlags, urlPage): PaginationManual => {
                const currentPage = Math.max(filters.page || 1, urlPage)

                const hasNextPage = featureFlags.count > currentPage * FLAGS_PER_PAGE
                const hasPreviousPage = currentPage > 1
                const needsPagination = featureFlags.count > FLAGS_PER_PAGE

                return {
                    controlled: true,
                    pageSize: FLAGS_PER_PAGE,
                    currentPage,
                    entryCount: featureFlags.count,
                    onForward:
                        needsPagination && hasNextPage
                            ? () => {
                                  experimentsLogic.actions.setFeatureFlagModalFilters({ page: currentPage + 1 })
                              }
                            : undefined,
                    onBackward:
                        needsPagination && hasPreviousPage
                            ? () => {
                                  experimentsLogic.actions.setFeatureFlagModalFilters({
                                      page: Math.max(1, currentPage - 1),
                                  })
                              }
                            : undefined,
                }
            },
        ],
        shouldShowEmptyState: [
            (s) => [s.experimentsLoading, s.experiments, s.filters],
            (experimentsLoading, experiments, filters): boolean => {
                return !experimentsLoading && experiments.results.length === 0 && objectsEqual(filters, DEFAULT_FILTERS)
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
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'experiments',
                    name: 'Experiments',
                    iconType: 'experiment',
                },
            ],
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                activity_scope: ActivityScope.EXPERIMENT,
            }),
        ],
    }),
    afterMount(({ actions, values }) => {
        actions.loadExperiments()
        actions.loadExperimentsStats()
        // Sync modal page with URL on mount
        const urlPage = values.featureFlagModalPageFromURL
        if (urlPage !== 1) {
            actions.setFeatureFlagModalFilters({ page: urlPage })
        } else {
            actions.loadFeatureFlagModalFeatureFlags()
        }
    }),
    actionToUrl(({ values }) => {
        const changeUrl = ():
            | [
                  string,
                  Record<string, any>,
                  Record<string, any>,
                  {
                      replace: boolean
                  },
              ]
            | void => {
            const searchParams: Record<string, string | number | boolean> = {
                ...values.filters,
            }

            if (values.tab !== ExperimentsTabs.All) {
                searchParams['tab'] = values.tab
            }

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        }

        const changeFeatureFlagModalUrl = ():
            | [
                  string,
                  Record<string, any>,
                  Record<string, any>,
                  {
                      replace: boolean
                  },
              ]
            | void => {
            const searchParams: Record<string, string | number | boolean> = {
                ...values.filters,
            }

            if (values.tab !== ExperimentsTabs.All) {
                searchParams['tab'] = values.tab
            }

            // Add feature flag modal page to URL if not page 1
            const modalPage = values.featureFlagModalFilters.page || 1
            if (modalPage !== 1) {
                searchParams['ff_page'] = modalPage
            }

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        }

        return {
            setExperimentsFilters: changeUrl,
            setExperimentsTab: changeUrl,
            setFeatureFlagModalFilters: changeFeatureFlagModalUrl,
            resetFeatureFlagModalFilters: changeFeatureFlagModalUrl,
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

            const { page, search, status, created_by_id, order, archived } = searchParams
            const pageFiltersFromUrl: Partial<ExperimentsFilters> = {
                search,
                created_by_id,
                order,
            }

            pageFiltersFromUrl.status = status || 'all'
            pageFiltersFromUrl.page = page !== undefined ? parseInt(page) : 1
            pageFiltersFromUrl.archived = String(archived) === 'true'

            actions.setExperimentsFilters({ ...DEFAULT_FILTERS, ...pageFiltersFromUrl })
        },
    })),
])
