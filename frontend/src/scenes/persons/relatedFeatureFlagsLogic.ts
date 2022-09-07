import Fuse from 'fuse.js'
import { actions, connect, events, kea, key, path, props, selectors, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { FeatureFlagReleaseType, FeatureFlagType } from '~/types'
import { FeatureFlagMatchReason } from './RelatedFeatureFlags'

import type { relatedFeatureFlagsLogicType } from './relatedFeatureFlagsLogicType'
export interface RelatedFeatureFlag extends FeatureFlagType {
    value: boolean
    evaluation: FeatureFlagEvaluationType
}

export interface FeatureFlagEvaluationType {
    reason: string
    condition_index?: number
}

interface RelatedFeatureFlagResponse {
    [key: string]: {
        value: boolean
        evaluation: FeatureFlagEvaluationType
    }
}

interface RelatedFlagsFilters {
    type: FeatureFlagEvaluationType
    active: boolean
    reason: FeatureFlagMatchReason
}

export const relatedFeatureFlagsLogic = kea<relatedFeatureFlagsLogicType>([
    path(['scenes', 'persons', 'relatedFeatureFlagsLogic']),
    connect({ values: [teamLogic, ['currentTeamId'], featureFlagsLogic, ['featureFlags']] }),
    props(
        {} as {
            distinctId: string
        }
    ),
    key((props) => `${props.distinctId}`),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setFilters: (filters: Partial<RelatedFlagsFilters>, replace?: boolean) => ({ filters, replace }),
        loadRelatedFeatureFlags: true,
    }),
    loaders(({ values, props }) => ({
        relatedFeatureFlags: [
            null as RelatedFeatureFlagResponse | null,
            {
                loadRelatedFeatureFlags: async () => {
                    const response = await api.get(
                        `api/projects/${values.currentTeamId}/feature_flags/evaluation_reasons?${toParams({
                            distinct_id: props.distinctId,
                        })}`
                    )
                    return response
                },
            },
        ],
    })),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        filters: [
            {} as Partial<RelatedFlagsFilters>,
            {
                setFilters: (state, { filters, replace }) => {
                    if (replace) {
                        return { ...filters }
                    }
                    return { ...state, ...filters }
                },
            },
        ],
    }),
    selectors(() => ({
        mappedRelatedFeatureFlags: [
            (selectors) => [selectors.relatedFeatureFlags, selectors.featureFlags],
            (relatedFlags, featureFlags): RelatedFeatureFlag[] => {
                if (relatedFlags && featureFlags) {
                    const res = featureFlags.map((flag) => ({ ...relatedFlags[flag.key], ...flag }))
                    return res
                }
                return []
            },
        ],
        filteredMappedFlags: [
            (selectors) => [selectors.mappedRelatedFeatureFlags, selectors.searchTerm, selectors.filters],
            (featureFlags, searchTerm, filters) => {
                if (!searchTerm && Object.keys(filters).length === 0) {
                    return featureFlags
                }
                let searchedFlags: RelatedFeatureFlag[] = featureFlags
                if (searchTerm) {
                    searchedFlags = new Fuse(featureFlags, {
                        keys: ['key', 'name'],
                        threshold: 0.3,
                    })
                        .search(searchTerm)
                        .map((result) => result.item)
                }

                const { type, active, reason } = filters
                if (type) {
                    searchedFlags = searchedFlags.filter((flag) =>
                        type === FeatureFlagReleaseType.Variants
                            ? flag.filters.multivariate
                            : !flag.filters.multivariate
                    )
                }
                if (active) {
                    searchedFlags = searchedFlags.filter((flag) => (active === 'true' ? flag.active : !flag.active))
                }
                if (reason) {
                    searchedFlags = searchedFlags.filter((flag) => flag.evaluation.reason === reason)
                }
                return searchedFlags
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: actions.loadRelatedFeatureFlags,
    })),
])
