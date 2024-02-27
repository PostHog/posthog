import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { TaxonomicFilterGroupType, TaxonomicFilterProps } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'

import { groupsModel } from '~/models/groupsModel'
import {
    AnyPropertyFilter,
    FeatureFlagFilters,
    FeatureFlagGroupType,
    PropertyFilterType,
    UserBlastRadiusType,
} from '~/types'

import { teamLogic } from '../teamLogic'
import type { featureFlagReleaseConditionsLogicType } from './FeatureFlagReleaseConditionsLogicType'

// type Stringify<T> = {
//     [K in keyof T]: T[K] extends object ? Stringify<T[K]> : string;
// };
// TODO: Type onChange errors properly
export interface FeatureFlagReleaseConditionsLogicProps {
    filters: FeatureFlagFilters
    id?: string
    readOnly?: boolean
    // TODO: Check early access features don't break because of this refactor
    onChange?: (filters: FeatureFlagFilters, errors: any) => void
}

export const featureFlagReleaseConditionsLogic = kea<featureFlagReleaseConditionsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagReleaseConditionsLogic']),
    props({} as FeatureFlagReleaseConditionsLogicProps),
    key(({ id }) => id ?? 'unknown'),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupsTaxonomicTypes', 'aggregationLabel'],
            enabledFeaturesLogic,
            ['featureFlags as enabledFeatures'],
        ],
    }),
    actions({
        setAggregationGroupTypeIndex: (value: number | null) => ({ value }),
        addConditionSet: true,
        removeConditionSet: (index: number) => ({ index }),
        duplicateConditionSet: (index: number) => ({ index }),
        updateConditionSet: (
            index: number,
            newRolloutPercentage?: number,
            newProperties?: AnyPropertyFilter[],
            newVariant?: string | null
        ) => ({
            index,
            newRolloutPercentage,
            newProperties,
            newVariant,
        }),
        setAffectedUsers: (index: number, count?: number) => ({ index, count }),
        setTotalUsers: (count: number) => ({ count }),
        calculateBlastRadius: true,
    }),
    reducers(({ props }) => ({
        filters: [
            props.filters,
            {
                setAggregationGroupTypeIndex: (state, { value }) => {
                    if (!state || state.aggregation_group_type_index == value) {
                        return state
                    }

                    const originalRolloutPercentage = state.groups[0].rollout_percentage

                    return {
                        ...state,
                        aggregation_group_type_index: value,
                        // :TRICKY: We reset property filters after changing what you're aggregating by.
                        groups: [{ properties: [], rollout_percentage: originalRolloutPercentage, variant: null }],
                    }
                },
                addConditionSet: (state) => {
                    if (!state) {
                        return state
                    }
                    const groups = [
                        ...(state?.groups || []),
                        { properties: [], rollout_percentage: undefined, variant: null },
                    ]
                    return { ...state, groups }
                },
                updateConditionSet: (state, { index, newRolloutPercentage, newProperties, newVariant }) => {
                    if (!state) {
                        return state
                    }

                    const groups = [...(state?.groups || [])]
                    if (newRolloutPercentage !== undefined) {
                        groups[index] = { ...groups[index], rollout_percentage: newRolloutPercentage }
                    }

                    if (newProperties !== undefined) {
                        groups[index] = { ...groups[index], properties: newProperties }
                    }

                    if (newVariant !== undefined) {
                        groups[index] = { ...groups[index], variant: newVariant }
                    }

                    return { ...state, groups }
                },
                removeConditionSet: (state, { index }) => {
                    if (!state) {
                        return state
                    }
                    const groups = [...state.groups]
                    groups.splice(index, 1)
                    return { ...state, groups }
                },
                duplicateConditionSet: (state, { index }) => {
                    if (!state) {
                        return state
                    }
                    const groups = state.groups.concat([state.groups[index]])
                    return { ...state, groups }
                },
            },
        ],
        affectedUsers: [
            { 0: -1 },
            {
                setAffectedUsers: (state, { index, count }) => ({
                    ...state,
                    [index]: count,
                }),
            },
        ],
        totalUsers: [
            null as number | null,
            {
                setTotalUsers: (_, { count }) => count,
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        updateConditionSet: async ({ index, newProperties }, breakpoint) => {
            if (newProperties) {
                // properties have changed, so we'll have to re-fetch affected users
                actions.setAffectedUsers(index, undefined)
            }

            if (
                !newProperties ||
                newProperties.some(
                    (property) =>
                        property.value === null ||
                        property.value === undefined ||
                        (Array.isArray(property.value) && property.value.length === 0)
                )
            ) {
                return
            }

            await breakpoint(1000) // in ms
            const response = await api.create(`api/projects/${values.currentTeamId}/feature_flags/user_blast_radius`, {
                condition: { properties: newProperties },
                group_type_index: values.filters?.aggregation_group_type_index ?? null,
            })
            actions.setAffectedUsers(index, response.users_affected)
            actions.setTotalUsers(response.total_users)
        },
        addConditionSet: () => {
            actions.setAffectedUsers(values.filters.groups.length - 1, -1)
        },
        calculateBlastRadius: async () => {
            const usersAffected: Promise<UserBlastRadiusType>[] = []

            values.filters?.groups?.forEach((condition, index) => {
                actions.setAffectedUsers(index, undefined)

                const properties = condition.properties
                if (
                    !properties ||
                    properties?.length === 0 ||
                    properties.some(
                        (property) =>
                            property.value === null ||
                            property.value === undefined ||
                            (Array.isArray(property.value) && property.value.length === 0)
                    )
                ) {
                    // don't compute for full rollouts or empty conditions
                    usersAffected.push(Promise.resolve({ users_affected: -1, total_users: -1 }))
                } else {
                    const responsePromise = api.create(
                        `api/projects/${values.currentTeamId}/feature_flags/user_blast_radius`,
                        {
                            condition,
                            group_type_index: values.filters?.aggregation_group_type_index ?? null,
                        }
                    )

                    usersAffected.push(responsePromise)
                }
            })

            const results = await Promise.all(usersAffected)
            // Create action for all users affected
            results.forEach((result, index) => {
                actions.setAffectedUsers(index, result.users_affected)
                if (result.total_users !== -1) {
                    actions.setTotalUsers(result.total_users)
                }
            })
        },
    })),
    selectors({
        // TODO: Decide if this should be here or not? Since flag needs this too for other places
        // aggregationTargetName: [
        //     (s) => [s.featureFlag, s.aggregationLabel],
        //     (featureFlag, aggregationLabel): string => {
        //         if (featureFlag && featureFlag.filters.aggregation_group_type_index != null) {
        //             return aggregationLabel(featureFlag.filters.aggregation_group_type_index).plural
        //         }
        //         return 'users'
        //     },
        // ],
        taxonomicGroupTypes: [
            (s) => [s.filters, s.groupsTaxonomicTypes, s.enabledFeatures],
            (filters, groupsTaxonomicTypes, enabledFeatures): TaxonomicFilterGroupType[] => {
                const baseGroupTypes = []
                const additionalGroupTypes = []
                const newFlagOperatorsEnabled = enabledFeatures[FEATURE_FLAGS.NEW_FEATURE_FLAG_OPERATORS]
                if (filters && filters.aggregation_group_type_index != null && groupsTaxonomicTypes.length > 0) {
                    baseGroupTypes.push(groupsTaxonomicTypes[filters.aggregation_group_type_index])

                    if (newFlagOperatorsEnabled) {
                        additionalGroupTypes.push(
                            `${TaxonomicFilterGroupType.GroupNamesPrefix}_${filters.aggregation_group_type_index}` as unknown as TaxonomicFilterGroupType
                        )
                    }
                } else {
                    baseGroupTypes.push(TaxonomicFilterGroupType.PersonProperties)
                    baseGroupTypes.push(TaxonomicFilterGroupType.Cohorts)

                    if (newFlagOperatorsEnabled) {
                        additionalGroupTypes.push(TaxonomicFilterGroupType.Metadata)
                    }
                }

                return [...baseGroupTypes, ...additionalGroupTypes]
            },
        ],
        // TODO: rename to filtersTaxonomicOptions
        featureFlagTaxonomicOptions: [
            (s) => [s.filters],
            (filters) => {
                if (filters && filters.aggregation_group_type_index != null) {
                    return {}
                }

                const taxonomicOptions: TaxonomicFilterProps['optionsFromProp'] = {
                    [TaxonomicFilterGroupType.Metadata]: [
                        { name: 'distinct_id', propertyFilterType: PropertyFilterType.Person },
                    ],
                }
                return taxonomicOptions
            },
        ],
        propertySelectErrors: [
            (s) => [s.filters],
            (filters) => {
                return filters?.groups?.map(({ properties, rollout_percentage }: FeatureFlagGroupType) => ({
                    properties: properties?.map((property: AnyPropertyFilter) => ({
                        value:
                            property.value === null ||
                            property.value === undefined ||
                            (Array.isArray(property.value) && property.value.length === 0)
                                ? "Property filters can't be empty"
                                : undefined,
                    })),
                    rollout_percentage:
                        rollout_percentage === undefined ? 'You need to set a rollout % value' : undefined,
                    variant: null,
                }))
            },
        ],
        computeBlastRadiusPercentage: [
            (s) => [s.affectedUsers, s.totalUsers],
            (affectedUsers, totalUsers) => (rolloutPercentage, index) => {
                let effectiveRolloutPercentage = rolloutPercentage
                if (
                    rolloutPercentage === undefined ||
                    rolloutPercentage === null ||
                    (rolloutPercentage && rolloutPercentage > 100)
                ) {
                    effectiveRolloutPercentage = 100
                }

                if (
                    affectedUsers[index] === -1 ||
                    totalUsers === -1 ||
                    !totalUsers ||
                    affectedUsers[index] === undefined
                ) {
                    return effectiveRolloutPercentage
                }

                let effectiveTotalUsers = totalUsers
                if (effectiveTotalUsers === 0) {
                    effectiveTotalUsers = 1
                }

                return effectiveRolloutPercentage * (affectedUsers[index] / effectiveTotalUsers)
            },
        ],
    }),
    subscriptions(({ props, values }) => ({
        filters: (value: FeatureFlagFilters, oldValue: FeatureFlagFilters): void => {
            // TODO: Consider JSON stringify for better equality check?
            if (value !== oldValue) {
                props.onChange?.(value, values.propertySelectErrors)
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (!props.readOnly) {
            actions.calculateBlastRadius()
        }
    }),
])
