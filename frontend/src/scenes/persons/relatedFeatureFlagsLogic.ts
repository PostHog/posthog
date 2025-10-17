import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { toParams } from 'lib/utils'
import { FeatureFlagsFilters, featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { FeatureFlagReleaseType, FeatureFlagType } from '~/types'

import { FeatureFlagMatchReason } from './RelatedFeatureFlags'
import type { relatedFeatureFlagsLogicType } from './relatedFeatureFlagsLogicType'

export interface RelatedFeatureFlag extends FeatureFlagType {
    value: boolean | string
    evaluation: FeatureFlagEvaluationType
}

export interface FeatureFlagEvaluationType {
    reason: FeatureFlagMatchReason
    condition_index?: number
}

export interface RelatedFeatureFlagResponse {
    [key: string]: {
        value: boolean | string
        evaluation: FeatureFlagEvaluationType
    }
}

export interface RelatedFlagsFilters {
    type?: string
    active?: string
    reason?: string
}

export const relatedFeatureFlagsLogic = kea<relatedFeatureFlagsLogicType>([
    path(['scenes', 'persons', 'relatedFeatureFlagsLogic']),
    props(
        {} as {
            distinctId: string | null
            groupTypeIndex?: number
            groups?: { [key: string]: string }
        }
    ),
    key((props) => `${props.distinctId}`),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], featureFlagsLogic, ['featureFlags', 'pagination']],
        actions: [featureFlagsLogic, ['setFeatureFlagsFilters', 'loadFeatureFlagsSuccess']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => {
            featureFlagsLogic.actions.setFeatureFlagsFilters({ search: searchTerm })
            return { searchTerm }
        },
        setFilters: (filters: Partial<RelatedFlagsFilters>, replace?: boolean) => ({ filters, replace }),
        loadRelatedFeatureFlags: true,
    }),
    loaders(({ values, props }) => ({
        relatedFeatureFlags: [
            null as RelatedFeatureFlagResponse | null,
            {
                loadRelatedFeatureFlags: async () => {
                    const response = await api.get(
                        `api/projects/${values.currentProjectId}/feature_flags/evaluation_reasons?${toParams({
                            ...(props.distinctId ? { distinct_id: props.distinctId } : {}),
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
    selectors(({ props }) => ({
        mappedRelatedFeatureFlags: [
            (selectors) => [selectors.relatedFeatureFlags, selectors.featureFlags],
            (relatedFlags, featureFlags): RelatedFeatureFlag[] => {
                if (relatedFlags && featureFlags) {
                    let flags = featureFlags.results
                        .map((flag) => ({ ...relatedFlags[flag.key], ...flag }))
                        .filter((flag) => flag.evaluation !== undefined)

                    // return related feature flags for group property targeting or person property targeting, but not both
                    if (props.groupTypeIndex !== undefined && props.groups && Object.keys(props.groups).length > 0) {
                        flags = flags.filter(
                            (flag) =>
                                flag.filters.aggregation_group_type_index !== undefined &&
                                flag.filters.aggregation_group_type_index !== null &&
                                flag.filters.aggregation_group_type_index === props.groupTypeIndex
                        )
                    } else {
                        flags = flags.filter(
                            (flag) =>
                                flag.filters.aggregation_group_type_index === undefined ||
                                flag.filters.aggregation_group_type_index === null
                        )
                    }

                    return flags
                }
                return []
            },
        ],
        filteredMappedFlags: [
            (selectors) => [selectors.mappedRelatedFeatureFlags, selectors.filters],
            (featureFlags, filters: Partial<RelatedFlagsFilters>) => {
                if (Object.keys(filters).length === 0) {
                    return featureFlags
                }

                const { reason } = filters
                let filteredFlags = featureFlags
                if (reason) {
                    filteredFlags = filteredFlags.filter((flag) =>
                        reason === 'not matched'
                            ? flag.evaluation.reason !== FeatureFlagMatchReason.ConditionMatch
                            : flag.evaluation.reason === FeatureFlagMatchReason.ConditionMatch
                    )
                }
                return filteredFlags
            },
        ],
    })),
    listeners(({ values, actions }) => ({
        setFilters: ({ filters, replace }) => {
            const apiFilters: FeatureFlagsFilters = {}

            if (replace) {
                const currentFilters = values.filters

                if (!('type' in filters) && currentFilters.type) {
                    apiFilters.type = undefined
                }

                if (!('active' in filters) && currentFilters.active) {
                    apiFilters.active = undefined
                }
            }

            if ('type' in filters && filters.type !== undefined) {
                if (filters.type === FeatureFlagReleaseType.ReleaseToggle) {
                    apiFilters.type = 'boolean'
                } else if (filters.type === FeatureFlagReleaseType.Variants) {
                    apiFilters.type = 'multivariant'
                }
            }

            if ('active' in filters && filters.active !== undefined) {
                apiFilters.active = filters.active
            }

            if (Object.keys(apiFilters).length > 0 || replace) {
                actions.setFeatureFlagsFilters({ ...apiFilters, page: 1 }, replace)
            }
        },
        loadFeatureFlagsSuccess: () => {
            actions.loadRelatedFeatureFlags()
        },
    })),
    events(({ actions }) => ({
        afterMount: actions.loadRelatedFeatureFlags,
    })),
    urlToAction(({ actions }) => ({
        [urls.personByUUID('*', false)]: async (_, searchParams) => {
            const page = searchParams['page']
            if (page !== undefined) {
                actions.setFeatureFlagsFilters({ page: parseInt(page) })
            }
        },
    })),
])
