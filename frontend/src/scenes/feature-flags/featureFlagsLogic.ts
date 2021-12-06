import { kea } from 'kea'
import api from 'lib/api'
import Fuse from 'fuse.js'
import { featureFlagsLogicType } from './featureFlagsLogicType'
import { Breadcrumb, FeatureFlagType } from '~/types'
import { teamLogic } from '../teamLogic'
import { urls } from 'scenes/urls'

export const featureFlagsLogic = kea<featureFlagsLogicType>({
    path: ['scenes', 'feature-flags', 'featureFlagsLogic'],
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },
    actions: {
        updateFlag: (flag: FeatureFlagType) => ({ flag }),
        deleteFlag: (id: number) => ({ id }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSelectedTag: (selectedTag: string) => ({ selectedTag }),
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
        featureFlagsTags: {
            __default: [] as string[],
            loadFeatureFlagTags: async () => {
                const response = await api.get(`api/projects/${values.currentTeamId}/feature_flags/tags`)
                return response as string[]
            },
        },
    }),
    selectors: {
        searchedFeatureFlags: [
            (selectors) => [selectors.featureFlags, selectors.searchTerm, selectors.selectedTag],
            (featureFlags, searchTerm, selectedTag) => {
                if (!searchTerm && !selectedTag) {
                    return featureFlags
                }

                if (!searchTerm && selectedTag === 'all-tags') {
                    return featureFlags
                }

                const filteredFlagsByTags = selectedTag
                    ? featureFlags.filter((item) => item.tags.includes(selectedTag))
                    : featureFlags

                if (!searchTerm) {
                    return filteredFlagsByTags
                }

                return new Fuse(filteredFlagsByTags, {
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
                    name: 'Feature flags',
                    path: urls.featureFlags(),
                },
            ],
        ],
    },
    reducers: {
        searchTerm: {
            setSearchTerm: (_, { searchTerm }) => searchTerm,
        },
        selectedTag: {
            setSelectedTag: (_, { selectedTag }) => selectedTag,
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
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
            actions.loadFeatureFlagTags()
        },
    }),
})
