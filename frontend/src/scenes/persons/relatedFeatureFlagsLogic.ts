import Fuse from 'fuse.js'
import { actions, connect, events, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { FeatureFlagReleaseType, FeatureFlagType } from '~/types'

import { FeatureFlagMatchReason } from './RelatedFeatureFlags'
import type { relatedFeatureFlagsLogicType } from './relatedFeatureFlagsLogicType'
export interface RelatedFeatureFlag extends FeatureFlagType {
    value: boolean | string
    evaluation: FeatureFlagEvaluationType
}

export interface FeatureFlagEvaluationType {
    reason: string
    condition_index?: number
}

export interface RelatedFeatureFlagResponse {
    [key: string]: {
        value: boolean | string
        evaluation: FeatureFlagEvaluationType
    }
}

export interface RelatedFlagsFilters {
    type: string
    active: string
    reason: string
}

export const relatedFeatureFlagsLogic = kea<relatedFeatureFlagsLogicType>([
    path(['scenes', 'persons', 'relatedFeatureFlagsLogic']),
    connect({ values: [teamLogic, ['currentTeamId'], featureFlagsLogic, ['featureFlags']] }),
    props(
        {} as {
            distinctId: string
            groups?: { [key: string]: string }
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
                            ...(props.groups ? { groups: props.groups } : {}),
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
                    return featureFlags.map((flag) => ({ ...relatedFlags[flag.key], ...flag }))
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
                    searchedFlags = searchedFlags.filter((flag) =>
                        reason === 'not matched'
                            ? flag.evaluation.reason !== FeatureFlagMatchReason.ConditionMatch
                            : flag.evaluation.reason === FeatureFlagMatchReason.ConditionMatch
                    )
                }
                return searchedFlags
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: actions.loadRelatedFeatureFlags,
    })),
])
