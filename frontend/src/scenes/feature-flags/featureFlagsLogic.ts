import { kea } from 'kea'
import api from 'lib/api'
import Fuse from 'fuse.js'
import type { featureFlagsLogicType } from './featureFlagsLogicType'
import { Breadcrumb, FeatureFlagType } from '~/types'
import { teamLogic } from '../teamLogic'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'
import { toParams } from 'lib/utils'

export enum FeatureFlagsTabs {
    OVERVIEW = 'overview',
    HISTORY = 'history',
}

export interface FeatureFlagsFilters {
    active: boolean
    created_by: string
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
        setActiveTab: (tabKey: FeatureFlagsTabs) => ({ tabKey }),
        setFeatureFlagsFilters: (filters: Partial<FeatureFlagsFilters>, replace?: boolean) => ({ filters, replace }),
    },
    loaders: ({ values }) => ({
        featureFlags: {
            __default: [] as FeatureFlagType[],
            loadFeatureFlags: async () => {
                const params = values.filters
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/feature_flags/?${toParams(params)}`
                )
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
        uniqueCreators: [
            (selectors) => [selectors.featureFlags],
            (featureFlags) => {
                const creators = {}
                featureFlags.forEach((flag: FeatureFlagType) => {
                    if (flag.created_by) {
                        if (!creators[flag.created_by.email]) {
                            creators[flag.created_by.email] = flag.created_by.first_name
                        }
                    }
                })
                const response = [{ label: 'Any user', value: 'all' }]
                for (const [email, first_name] of Object.entries(creators)) {
                    response.push({ label: first_name, value: email })
                }
                return response
            },
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
            FeatureFlagsTabs.OVERVIEW as FeatureFlagsTabs,
            {
                setActiveTab: (state, { tabKey }) =>
                    Object.values<string>(FeatureFlagsTabs).includes(tabKey) ? tabKey : state,
            },
        ],
        filters: [
            // null as Partial<SavedInsightFilters> | null,
            null as Partial<FeatureFlagsFilters> | null,
            {
                setFeatureFlagsFilters: (state, { filters, replace }) => {
                    if (replace) {
                        return { ...filters }
                    }
                    return { ...state, ...filters }
                },
                // cleanFilters({
                //     ...(merge ? state || {} : {}),
                //     ...filters,
                //     // Reset page on filter change EXCEPT if it's page or view that's being updated
                //     ...('page' in filters || 'layoutView' in filters ? {} : { page: 1 }),
                // }),
            },
        ],
    },
    listeners: ({ actions }) => ({
        setFeatureFlagsFilters: () => {
            actions.loadFeatureFlags()
        },
    }),
    actionToUrl: ({ values }) => ({
        setActiveTab: () => {
            const searchParams = {
                ...router.values.searchParams,
            }

            let replace = false // set a page in history
            if (!searchParams['tab'] && values.activeTab === FeatureFlagsTabs.OVERVIEW) {
                // we are on the overview page, and have clicked the overview tab, don't set history
                replace = true
            }
            searchParams['tab'] = values.activeTab

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace }]
        },
    }),
    urlToAction: ({ actions, values }) => ({
        [urls.featureFlags()]: async (_, searchParams) => {
            const tabInURL = searchParams['tab']

            if (!tabInURL) {
                if (values.activeTab !== FeatureFlagsTabs.OVERVIEW) {
                    actions.setActiveTab(FeatureFlagsTabs.OVERVIEW)
                }
            } else if (tabInURL !== values.activeTab) {
                actions.setActiveTab(tabInURL)
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
        },
    }),
})
