import { kea } from 'kea'
import api from 'lib/api'
import Fuse from 'fuse.js'
import { featureFlagsLogicType } from './featureFlagsLogicType'
import { Breadcrumb, FeatureFlagType } from '~/types'
import { teamLogic } from '../teamLogic'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'

export enum FeatureFlagsTabs {
    OVERVIEW = 'overview',
    HISTORY = 'history',
}

export const featureFlagsLogic = kea<featureFlagsLogicType>({
    path: ['scenes', 'feature-flags', 'featureFlagsLogic'],
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },
    actions: {
        updateFlag: (flag: FeatureFlagType) => ({ flag }),
        deleteFlag: (id: number) => ({ id }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setActiveTab: (tabKey: string) => ({ tabKey }),
        setHistoryPage: (page: number) => ({ page }),
    },
    loaders: ({ values }) => ({
        featureFlags: {
            __default: [] as FeatureFlagType[],
            loadFeatureFlags: async () => {
                const response = await api.get(`api/projects/${values.currentTeamId}/feature_flags/`)
                return response.results as FeatureFlagType[]
            },
            updateFeatureFlag: async ({ id, payload }: { id: number; payload: Partial<FeatureFlagType> }) => {
                const response = await api.update(`api/projects/${values.currentTeamId}/feature_flags/${id}`, payload)
                return [...values.featureFlags].map((flag) => (flag.id === response.id ? response : flag))
            },
        },
    }),
    selectors: {
        searchedFeatureFlags: [
            (selectors) => [selectors.featureFlags, selectors.searchTerm],
            (featureFlags, searchTerm) => {
                if (!searchTerm) {
                    return featureFlags
                }
                return new Fuse(featureFlags, {
                    keys: ['key', 'name'],
                    threshold: 0.3,
                })
                    .search(searchTerm)
                    .map((result) => result.item)
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    name: 'Feature Flags',
                    path: urls.featureFlags(),
                },
            ],
        ],
    },
    reducers: {
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
            FeatureFlagsTabs.OVERVIEW,
            {
                setActiveTab: (state, { tabKey }) =>
                    Object.values<string>(FeatureFlagsTabs).includes(tabKey) ? tabKey : state,
            },
        ],
        historyPage: [null as number | null, { setHistoryPage: (_, { page }) => page }],
    },
    actionToUrl: ({ values }) => ({
        setActiveTab: () => {
            const searchParams = {
                ...router.values.searchParams,
                tab: values.activeTab,
            }
            if (values.activeTab !== FeatureFlagsTabs.HISTORY) {
                delete searchParams['page']
            }
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
    }),
    urlToAction: ({ actions, values }) => ({
        [urls.featureFlags()]: async (_, searchParams) => {
            const tabInURL = searchParams['tab']
            if (tabInURL && tabInURL !== values.activeTab) {
                actions.setActiveTab(tabInURL)
            }
            const pageInURL = searchParams['page']
            if (pageInURL && values.activeTab === FeatureFlagsTabs.HISTORY) {
                actions.setHistoryPage(pageInURL)
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
        },
    }),
})
