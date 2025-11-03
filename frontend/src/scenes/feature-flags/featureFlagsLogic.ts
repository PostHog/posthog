import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { PaginationManual } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { objectsEqual, parseTagsFilter, toParams } from 'lib/utils'
import { projectLogic } from 'scenes/projectLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivationTask } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb, FeatureFlagType } from '~/types'

import type { featureFlagsLogicType } from './featureFlagsLogicType'

export const FLAGS_PER_PAGE = 100

export enum FeatureFlagsTab {
    OVERVIEW = 'overview',
    HISTORY = 'history',
    EXPOSURE = 'exposure',
    Analysis = 'analysis',
    USAGE = 'usage',
    PERMISSIONS = 'permissions',
    PROJECTS = 'projects',
    SCHEDULE = 'schedule',
}

export interface FeatureFlagsResult extends CountedPaginatedResponse<FeatureFlagType> {
    /* not in the API response */
    filters?: FeatureFlagsFilters | null
}

export interface FeatureFlagsFilters {
    active?: string
    created_by_id?: number
    type?: string
    search?: string
    order?: string
    page?: number
    evaluation_runtime?: string
    tags?: string[]
}

const DEFAULT_FILTERS: FeatureFlagsFilters = {
    active: undefined,
    created_by_id: undefined,
    type: undefined,
    search: undefined,
    order: undefined,
    page: 1,
    evaluation_runtime: undefined,
    tags: undefined,
}

export interface FlagLogicProps {
    flagPrefix?: string // used to filter flags by prefix e.g. for the user interview flags
}

export const featureFlagsLogic = kea<featureFlagsLogicType>([
    props({} as FlagLogicProps),
    path(['scenes', 'feature-flags', 'featureFlagsLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        updateFlag: (flag: FeatureFlagType) => ({ flag }),
        deleteFlag: (id: number) => ({ id }),
        setActiveTab: (tabKey: FeatureFlagsTab) => ({ tabKey }),
        setFeatureFlagsFilters: (filters: Partial<FeatureFlagsFilters>, replace?: boolean) => ({ filters, replace }),
        closeEnrichAnalyticsNotice: true,
    }),
    loaders(({ values }) => ({
        featureFlags: [
            { results: [], count: 0, filters: DEFAULT_FILTERS, offset: 0 } as FeatureFlagsResult,
            {
                loadFeatureFlags: async () => {
                    const response = await api.get(
                        `api/projects/${values.currentProjectId}/feature_flags/?${toParams(values.paramsFromFilters)}`
                    )

                    return {
                        ...response,
                        offset: values.paramsFromFilters.offset,
                    }
                },
                updateFeatureFlag: async ({ id, payload }: { id: number; payload: Partial<FeatureFlagType> }) => {
                    const response = await api.update(
                        `api/projects/${values.currentProjectId}/feature_flags/${id}`,
                        payload
                    )
                    const updatedFlags = [...values.featureFlags.results].map((flag) =>
                        flag.id === response.id ? response : flag
                    )
                    return { ...values.featureFlags, results: updatedFlags }
                },
            },
        ],
    })),
    reducers({
        featureFlags: {
            updateFlag: (state, { flag }) => ({
                ...state,
                results: state.results.map((stateFlag) => (stateFlag.id === flag.id ? flag : stateFlag)),
            }),
            deleteFlag: (state, { id }) => ({
                ...state,
                count: state.count - 1,
                results: state.results.filter((flag) => flag.id !== id),
            }),
        },
        activeTab: [
            FeatureFlagsTab.OVERVIEW as FeatureFlagsTab,
            {
                setActiveTab: (state, { tabKey }) =>
                    Object.values<string>(FeatureFlagsTab).includes(tabKey) ? tabKey : state,
            },
        ],
        filters: [
            DEFAULT_FILTERS,
            {
                setFeatureFlagsFilters: (state, { filters, replace }) => {
                    if (replace) {
                        return { ...filters }
                    }
                    return { ...state, ...filters }
                },
            },
        ],
        enrichAnalyticsNoticeAcknowledged: [
            false,
            { persist: true },
            {
                closeEnrichAnalyticsNotice: () => true,
            },
        ],
    }),
    selectors({
        count: [(selectors) => [selectors.featureFlags], (featureFlags) => featureFlags.count],
        paramsFromFilters: [
            (s) => [s.filters],
            (filters: FeatureFlagsFilters) => ({
                ...filters,
                limit: FLAGS_PER_PAGE,
                offset: filters.page ? (filters.page - 1) * FLAGS_PER_PAGE : 0,
            }),
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.FeatureFlags,
                    name: 'Feature flags',
                    path: urls.featureFlags(),
                    iconType: 'feature_flag',
                },
            ],
        ],
        // Check to see if any non-default filters are being used
        shouldShowEmptyState: [
            (s) => [s.featureFlagsLoading, s.featureFlags, s.filters],
            (featureFlagsLoading, featureFlags, filters): boolean => {
                return (
                    !featureFlagsLoading && featureFlags.results.length <= 0 && objectsEqual(filters, DEFAULT_FILTERS)
                )
            },
        ],
        pagination: [
            (s) => [s.filters, s.count],
            (filters, count): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: FLAGS_PER_PAGE,
                    currentPage: filters.page || 1,
                    entryCount: count,
                }
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                activity_scope: ActivityScope.FEATURE_FLAG,
            }),
        ],
    }),
    listeners(({ actions, values }) => ({
        setFeatureFlagsFilters: async (_, breakpoint) => {
            if (values.activeTab === FeatureFlagsTab.OVERVIEW) {
                await breakpoint(300)
                actions.loadFeatureFlags()
            }
        },
        setActiveTab: () => {
            // Don't carry over pagination from previous tab
            actions.setFeatureFlagsFilters({ page: 1 }, true)
        },
        loadFeatureFlagsSuccess: () => {
            if (values.featureFlags.results.length > 0) {
                activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.CreateFeatureFlag)
            }
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
                  },
              ]
            | void => {
            const searchParams: Record<string, string | number | string[]> = {
                ...values.filters,
            }

            let replace = false // set a page in history
            if (!searchParams['tab'] && values.activeTab === FeatureFlagsTab.OVERVIEW) {
                // we are on the overview page, and have clicked the overview tab, don't set history
                replace = true
            }
            searchParams['tab'] = values.activeTab

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace }]
        }

        return {
            setFeatureFlagsFilters: changeUrl,
            setActiveTab: changeUrl,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.featureFlags()]: async (_, searchParams) => {
            const tabInURL = searchParams['tab']

            if (!tabInURL) {
                if (values.activeTab !== FeatureFlagsTab.OVERVIEW) {
                    actions.setActiveTab(FeatureFlagsTab.OVERVIEW)
                }
            } else if (tabInURL !== values.activeTab) {
                actions.setActiveTab(tabInURL)
            }

            const { page, created_by_id, active, type, search, order, evaluation_runtime, tags } = searchParams
            const pageFiltersFromUrl: Partial<FeatureFlagsFilters> = {
                created_by_id,
                type,
                search,
                order,
                evaluation_runtime,
                tags: parseTagsFilter(tags),
            }

            pageFiltersFromUrl.active = active !== undefined ? String(active) : undefined
            pageFiltersFromUrl.page = page !== undefined ? parseInt(page) : undefined

            actions.setFeatureFlagsFilters({ ...DEFAULT_FILTERS, ...pageFiltersFromUrl })
        },
    })),
])
