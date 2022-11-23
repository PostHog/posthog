import { kea } from 'kea'
import api from 'lib/api'
import Fuse from 'fuse.js'
import type { featureFlagsLogicType } from './featureFlagsLogicType'
import { Breadcrumb, FeatureFlagType } from '~/types'
import { teamLogic } from '../teamLogic'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'
import { LemonSelectOption } from 'lib/components/LemonSelect'

export enum FeatureFlagsTabs {
    OVERVIEW = 'overview',
    HISTORY = 'history',
    EXPOSURE = 'exposure',
}

export interface FeatureFlagsFilters {
    active: string
    created_by: string
}

interface FeatureFlagCreators {
    [id: string]: string
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
                const response = await api.get(`api/projects/${values.currentTeamId}/feature_flags`)
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
            (selectors) => [selectors.featureFlags, selectors.searchTerm, selectors.filters],
            (featureFlags, searchTerm, filters) => {
                if (!searchTerm && Object.keys(filters).length === 0) {
                    return featureFlags
                }
                let searchedFlags = featureFlags
                if (searchTerm) {
                    searchedFlags = new Fuse(featureFlags, {
                        keys: ['key', 'name'],
                        threshold: 0.3,
                    })
                        .search(searchTerm)
                        .map((result) => result.item)
                }

                const { active, created_by } = filters
                if (active) {
                    searchedFlags = searchedFlags.filter((flag) => (active === 'true' ? flag.active : !flag.active))
                }
                if (created_by) {
                    searchedFlags = searchedFlags.filter((flag) => flag.created_by?.id === parseInt(created_by))
                }
                return searchedFlags
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
                const creators: FeatureFlagCreators = {}
                for (const flag of featureFlags) {
                    if (flag.created_by) {
                        if (!creators[flag.created_by.id]) {
                            creators[flag.created_by.id] = flag.created_by.first_name
                        }
                    }
                }
                const response: LemonSelectOption<string>[] = [
                    { label: 'Any user', value: 'any' },
                    ...Object.entries(creators).map(([id, first_name]) => ({ label: first_name, value: id })),
                ]
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
