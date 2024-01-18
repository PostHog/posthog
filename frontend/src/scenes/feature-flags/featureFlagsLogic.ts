import Fuse from 'fuse.js'
import { actions, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, FeatureFlagType } from '~/types'

import { teamLogic } from '../teamLogic'
import type { featureFlagsLogicType } from './featureFlagsLogicType'

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

export interface FeatureFlagsFilters {
    active: string
    created_by: number
    type: string
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
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setActiveTab: (tabKey: FeatureFlagsTab) => ({ tabKey }),
        setFeatureFlagsFilters: (filters: Partial<FeatureFlagsFilters>, replace?: boolean) => ({ filters, replace }),
        closeEnrichAnalyticsNotice: true,
    }),
    loaders(({ values }) => ({
        featureFlags: {
            __default: [] as FeatureFlagType[],
            loadFeatureFlags: async () => {
                const response = await api.get(`api/projects/${values.currentTeamId}/feature_flags/?limit=300`)
                return response.results as FeatureFlagType[]
            },
            updateFeatureFlag: async ({ id, payload }: { id: number; payload: Partial<FeatureFlagType> }) => {
                const response = await api.update(`api/projects/${values.currentTeamId}/feature_flags/${id}`, payload)
                return [...values.featureFlags].map((flag) => (flag.id === response.id ? response : flag))
            },
        },
    })),
    reducers({
        searchTerm: {
            setSearchTerm: (_, { searchTerm }) => searchTerm,
        },
        featureFlags: {
            updateFlag: (state, { flag }) => {
                if (state.find(({ id }) => id === flag.id)) {
                    return state.map((stateFlag) => (stateFlag.id === flag.id ? flag : stateFlag))
                } else {
                    return [flag, ...state]
                }
            },
            deleteFlag: (state, { id }) => state.filter((flag) => flag.id !== id),
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
        searchedFeatureFlags: [
            (selectors) => [
                selectors.featureFlags,
                selectors.searchTerm,
                selectors.filters,
                (_, props) => props.flagPrefix,
            ],
            (featureFlags, searchTerm, filters, flagPrefix) => {
                let searchedFlags = featureFlags

                if (flagPrefix) {
                    searchedFlags = searchedFlags.filter((flag) => flag.key.startsWith(flagPrefix))
                }

                if (!searchTerm && Object.keys(filters).length === 0) {
                    return searchedFlags
                }

                if (searchTerm) {
                    searchedFlags = new Fuse(searchedFlags, {
                        keys: ['key', 'name'],
                        threshold: 0.3,
                    })
                        .search(searchTerm)
                        .map((result) => result.item)
                }

                const { active, created_by, type } = filters
                if (active) {
                    searchedFlags = searchedFlags.filter((flag) => (active === 'true' ? flag.active : !flag.active))
                }
                if (created_by) {
                    searchedFlags = searchedFlags.filter((flag) => flag.created_by?.id === created_by)
                }
                if (type === 'boolean') {
                    searchedFlags = searchedFlags.filter(
                        (flag) => flag.filters.multivariate?.variants?.length ?? 0 == 0
                    )
                }
                if (type === 'multivariant') {
                    searchedFlags = searchedFlags.filter((flag) => flag.filters.multivariate?.variants?.length ?? 0 > 0)
                }
                if (type === 'experiment') {
                    searchedFlags = searchedFlags.filter((flag) => flag.experiment_set?.length ?? 0 > 0)
                }

                return searchedFlags
            },
        ],
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
            (s) => [s.featureFlagsLoading, s.featureFlags],
            (featureFlagsLoading, featureFlags): boolean => {
                return !featureFlagsLoading && featureFlags.length <= 0
            },
        ],
    }),
    listeners(({ actions }) => ({
        setFeatureFlagsFilters: () => {
            actions.loadFeatureFlags()
        },
    })),
    actionToUrl(({ values }) => ({
        setActiveTab: () => {
            const searchParams = {
                ...router.values.searchParams,
            }

            let replace = false // set a page in history
            if (!searchParams['tab'] && values.activeTab === FeatureFlagsTab.OVERVIEW) {
                // we are on the overview page, and have clicked the overview tab, don't set history
                replace = true
            }
            searchParams['tab'] = values.activeTab

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace }]
        },
    })),
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
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
        },
    })),
])
