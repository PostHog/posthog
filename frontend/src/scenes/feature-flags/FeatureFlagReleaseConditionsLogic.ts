import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { isEmptyProperty } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType, TaxonomicFilterProps } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual, range } from 'lib/utils'

import { groupsModel } from '~/models/groupsModel'
import {
    AnyPropertyFilter,
    FeatureFlagFilters,
    FeatureFlagGroupType,
    GroupTypeIndex,
    PropertyFilterType,
    UserBlastRadiusType,
} from '~/types'

import { teamLogic } from '../teamLogic'
import type { featureFlagReleaseConditionsLogicType } from './FeatureFlagReleaseConditionsLogicType'

// TODO: Type onChange errors properly
export interface FeatureFlagReleaseConditionsLogicProps {
    filters: FeatureFlagFilters
    id?: string
    readOnly?: boolean
    onChange?: (filters: FeatureFlagFilters, errors: any) => void
}

export const featureFlagReleaseConditionsLogic = kea<featureFlagReleaseConditionsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagReleaseConditionsLogic']),
    props({} as FeatureFlagReleaseConditionsLogicProps),
    key(({ id }) => id ?? 'unknown'),
    connect({
        values: [teamLogic, ['currentTeamId'], groupsModel, ['groupTypes', 'aggregationLabel']],
    }),
    actions({
        setFilters: (filters: FeatureFlagFilters) => ({ filters }),
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
                setFilters: (_, { filters }) => ({ ...filters }),
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
            { 0: undefined } as Record<number, number | undefined>,
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
        duplicateConditionSet: async ({ index }, breakpoint) => {
            await breakpoint(1000) // in ms
            const valueForSourceCondition = values.affectedUsers[index]
            const newIndex = values.filters.groups.length - 1
            actions.setAffectedUsers(newIndex, valueForSourceCondition)
        },
        updateConditionSet: async ({ index, newProperties }, breakpoint) => {
            if (newProperties) {
                // properties have changed, so we'll have to re-fetch affected users
                actions.setAffectedUsers(index, undefined)
            }

            if (!newProperties || newProperties.some(isEmptyProperty)) {
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
        removeConditionSet: ({ index }) => {
            const previousLength = Object.keys(values.affectedUsers).length
            range(index, previousLength).map((idx) => {
                const count = previousLength - 1 === idx ? undefined : values.affectedUsers[idx + 1]
                actions.setAffectedUsers(idx, count)
            })
        },
        setAggregationGroupTypeIndex: () => {
            actions.calculateBlastRadius()
        },
        calculateBlastRadius: async () => {
            const usersAffected: Promise<UserBlastRadiusType>[] = []

            values.filters?.groups?.forEach((condition, index) => {
                actions.setAffectedUsers(index, undefined)

                const properties = condition.properties
                if (!properties || properties?.length === 0 || properties.some(isEmptyProperty)) {
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
        taxonomicGroupTypes: [
            (s) => [s.filters, s.groupTypes],
            (filters, groupTypes): TaxonomicFilterGroupType[] => {
                const targetGroupTypes = []
                const targetGroup =
                    filters?.aggregation_group_type_index != null
                        ? groupTypes.get(filters.aggregation_group_type_index as GroupTypeIndex)
                        : undefined
                if (targetGroup) {
                    targetGroupTypes.push(
                        `${TaxonomicFilterGroupType.GroupsPrefix}_${targetGroup?.group_type_index}` as unknown as TaxonomicFilterGroupType
                    )

                    targetGroupTypes.push(
                        `${TaxonomicFilterGroupType.GroupNamesPrefix}_${filters.aggregation_group_type_index}` as unknown as TaxonomicFilterGroupType
                    )
                } else {
                    targetGroupTypes.push(TaxonomicFilterGroupType.PersonProperties)
                    targetGroupTypes.push(TaxonomicFilterGroupType.Cohorts)
                    targetGroupTypes.push(TaxonomicFilterGroupType.Metadata)
                }

                return targetGroupTypes
            },
        ],
        aggregationTargetName: [
            (s) => [s.filters, s.aggregationLabel],
            (filters, aggregationLabel): string => {
                if (filters.aggregation_group_type_index != null) {
                    return aggregationLabel(filters.aggregation_group_type_index).plural
                }
                return 'users'
            },
        ],
        filtersTaxonomicOptions: [
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
                        value: isEmptyProperty(property) ? "Property filters can't be empty" : undefined,
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

                return effectiveRolloutPercentage * ((affectedUsers[index] ?? 0) / effectiveTotalUsers)
            },
        ],
    }),
    propsChanged(({ props, values, actions }) => {
        if (!objectsEqual(props.filters, values.filters)) {
            actions.setFilters(props.filters)
        }
    }),
    subscriptions(({ props, values }) => ({
        filters: (value: FeatureFlagFilters, oldValue: FeatureFlagFilters): void => {
            if (!objectsEqual(value, oldValue)) {
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
