import { PaginationManual } from '@posthog/lemon-ui'
import { actions, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { objectsEqual, toParams } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, FeatureFlagType } from '~/types'

import { teamLogic } from '../teamLogic'
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

export interface FeatureFlagsResult {
    results: FeatureFlagType[]
    count: number
    next?: string | null
    previous?: string | null
    /* not in the API response */
    filters?: FeatureFlagsFilters | null
}

export interface FeatureFlagsFilters {
    active: string
    created_by_id: number
    type: string
    search: string
    order: string
    page: number
}

export interface FlagLogicProps {
    flagPrefix?: string // used to filter flags by prefix e.g. for the user interview flags
}

export const featureFlagsLogic = kea<featureFlagsLogicType>([
    props({} as FlagLogicProps),
    path(['scenes', 'feature-flags', 'featureFlagsLogic']),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        updateFlag: (flag: FeatureFlagType) => ({ flag }),
        deleteFlag: (id: number) => ({ id }),
        setActiveTab: (tabKey: FeatureFlagsTab) => ({ tabKey }),
        setFeatureFlagsFilters: (filters: Partial<FeatureFlagsFilters>, replace?: boolean) => ({ filters, replace }),
        closeEnrichAnalyticsNotice: true,
    }),
    loaders(({ values }) => ({
        featureFlags: {
            __default: { results: [], count: 0, filters: null, offset: 0 } as FeatureFlagsResult,
            loadFeatureFlags: async () => {
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/feature_flags/?${toParams(values.paramsFromFilters)}`
                )

                return {
                    ...response,
                    offset: values.paramsFromFilters.offset,
                }
            },
            updateFeatureFlag: async ({ id, payload }: { id: number; payload: Partial<FeatureFlagType> }) => {
                const response = await api.update(`api/projects/${values.currentTeamId}/feature_flags/${id}`, payload)
                return [...values.featureFlags.results].map((flag) => (flag.id === response.id ? response : flag))
            },
        },
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
            {} as Partial<FeatureFlagsFilters>,
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
        // Check to see if any non-default filters are being used
        usingFilters: [(s) => [s.filters], (filters) => !objectsEqual(filters, { limit: FLAGS_PER_PAGE, offset: 0 })],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.FeatureFlags,
                    name: 'Feature flags',
                    path: urls.featureFlags(),
                },
            ],
        ],
        shouldShowEmptyState: [
            (s) => [s.featureFlagsLoading, s.featureFlags, s.usingFilters],
            (featureFlagsLoading, featureFlags, usingFilters): boolean => {
                return !featureFlagsLoading && featureFlags.results.length <= 0 && !usingFilters
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
    }),
    listeners(({ actions }) => ({
        setFeatureFlagsFilters: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadFeatureFlags()
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

            const pageInURL = searchParams['page']
            if (pageInURL) {
                actions.setFeatureFlagsFilters({ page: parseInt(pageInURL) })
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
        },
    })),
])
