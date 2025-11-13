import {
    actions,
    afterMount,
    connect,
    defaults,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { v4 as uuidv4 } from 'uuid'

import api from 'lib/api'
import { isEmptyProperty } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType, TaxonomicFilterProps } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils'
import { projectLogic } from 'scenes/projectLogic'

import { groupsModel } from '~/models/groupsModel'
import {
    AnyPropertyFilter,
    FeatureFlagEvaluationRuntime,
    FeatureFlagFilters,
    FeatureFlagGroupType,
    GroupTypeIndex,
    MultivariateFlagVariant,
    PropertyFilterType,
    UserBlastRadiusType,
} from '~/types'

import type { featureFlagReleaseConditionsLogicType } from './featureFlagReleaseConditionsLogicType'

// Helper function to move a condition set to a new index
function moveConditionSet<T>(groups: T[], index: number, newIndex: number): T[] {
    const updatedGroups = [...groups]
    const item = updatedGroups[index]
    updatedGroups.splice(index, 1)
    updatedGroups.splice(newIndex, 0, item)
    return updatedGroups
}

// TODO: Type onChange errors properly
export interface FeatureFlagReleaseConditionsLogicProps {
    filters: FeatureFlagFilters
    id?: string
    readOnly?: boolean
    onChange?: (filters: FeatureFlagFilters, errors: any) => void
    nonEmptyFeatureFlagVariants?: MultivariateFlagVariant[]
    isSuper?: boolean
    evaluationRuntime?: FeatureFlagEvaluationRuntime
}

export type FeatureFlagGroupTypeWithSortKey = FeatureFlagGroupType & { sort_key: string }

function ensureSortKeys(
    filters: FeatureFlagFilters
): FeatureFlagFilters & { groups: FeatureFlagGroupTypeWithSortKey[] } {
    return {
        ...filters,
        groups: filters.groups.map((group: FeatureFlagGroupType) => ({
            ...group,
            sort_key: group.sort_key ?? uuidv4(),
        })),
    }
}

export const featureFlagReleaseConditionsLogic = kea<featureFlagReleaseConditionsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagReleaseConditionsLogic']),
    props({} as FeatureFlagReleaseConditionsLogicProps),
    key(({ id, isSuper }) => {
        const key = `${id ?? 'unknown'}-${isSuper ? 'super' : 'normal'}`
        return key
    }),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], groupsModel, ['groupTypes', 'aggregationLabel']],
    })),
    actions({
        setFilters: (filters: FeatureFlagFilters) => ({ filters }),
        setAggregationGroupTypeIndex: (value: number | null) => ({ value }),
        addConditionSet: true,
        removeConditionSet: (index: number) => ({ index }),
        duplicateConditionSet: (index: number) => ({ index }),
        moveConditionSetUp: (index: number) => ({ index }),
        moveConditionSetDown: (index: number) => ({ index }),
        updateConditionSet: (
            index: number,
            newRolloutPercentage?: number,
            newProperties?: AnyPropertyFilter[],
            newVariant?: string | null,
            newDescription?: string | null
        ) => ({
            index,
            newRolloutPercentage,
            newProperties,
            newVariant,
            newDescription,
        }),
        setAffectedUsers: (sortKey: string, count?: number) => ({ sortKey, count }),
        setTotalUsers: (count: number) => ({ count }),
        calculateBlastRadius: true,
        loadAllFlagKeys: (flagIds: string[]) => ({ flagIds }),
        setFlagKeys: (flagKeys: Record<string, string>) => ({ flagKeys }),
        setFlagKeysLoading: (isLoading: boolean) => ({ isLoading }),
    }),
    defaults(({ props }) => ({
        filters: ensureSortKeys(props.filters),
    })),
    reducers(() => ({
        filters: {
            setFilters: (state, { filters }) => {
                // Preserve sort_keys from previous state when possible
                const groupsWithKeys = filters.groups.map(
                    (group: FeatureFlagGroupType, index: number): FeatureFlagGroupTypeWithSortKey => {
                        if (group.sort_key) {
                            return group as FeatureFlagGroupTypeWithSortKey
                        }
                        // Try to preserve sort_key from same index in previous state
                        const previousSortKey = state?.groups?.[index]?.sort_key
                        return {
                            ...group,
                            sort_key: previousSortKey ?? uuidv4(),
                        }
                    }
                )

                return { ...filters, groups: groupsWithKeys }
            },
            setAggregationGroupTypeIndex: (state, { value }) => {
                if (!state || state.aggregation_group_type_index == value) {
                    return state
                }

                const originalRolloutPercentage = state.groups[0].rollout_percentage

                return {
                    ...state,
                    aggregation_group_type_index: value,
                    // :TRICKY: We reset property filters after changing what you're aggregating by.
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: originalRolloutPercentage,
                            variant: null,
                            sort_key: uuidv4(),
                        },
                    ],
                }
            },
            addConditionSet: (state) => {
                if (!state) {
                    return state
                }
                const groups = [
                    ...(state?.groups || []),
                    { properties: [], rollout_percentage: undefined, variant: null, sort_key: uuidv4() },
                ]
                return { ...state, groups }
            },
            updateConditionSet: (state, { index, newRolloutPercentage, newProperties, newVariant, newDescription }) => {
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

                if (newDescription !== undefined) {
                    const description = newDescription && newDescription.trim() ? newDescription : null
                    groups[index] = { ...groups[index], description }
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
                const newGroup: FeatureFlagGroupTypeWithSortKey = {
                    ...state.groups[index],
                    sort_key: uuidv4(),
                }
                const groups: FeatureFlagGroupTypeWithSortKey[] = [...state.groups, newGroup]
                return { ...state, groups }
            },
            moveConditionSetDown: (state, { index }) => {
                if (!state || index >= state.groups.length - 1) {
                    return state
                }
                return { ...state, groups: moveConditionSet(state.groups, index, index + 1) }
            },
            moveConditionSetUp: (state, { index }) => {
                if (!state || index <= 0) {
                    return state
                }
                return { ...state, groups: moveConditionSet(state.groups, index, index - 1) }
            },
        },
        affectedUsers: [
            {} as Record<string, number | undefined>,
            {
                setAffectedUsers: (state, { sortKey, count }) => ({
                    ...state,
                    [sortKey]: count,
                }),
            },
        ],
        totalUsers: [
            null as number | null,
            {
                setTotalUsers: (_, { count }) => count,
            },
        ],
        flagKeyCache: [
            {} as Record<string, string>,
            {
                setFlagKeys: (state, { flagKeys }) => ({
                    ...state,
                    ...flagKeys,
                }),
            },
        ],
        flagKeyLoading: [
            false as boolean,
            {
                setFlagKeysLoading: (_, { isLoading }) => isLoading,
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setFilters: async () => {
            const { flagIds } = values
            if (flagIds.length > 0) {
                await actions.loadAllFlagKeys(flagIds)
            }
        },
        duplicateConditionSet: async ({ index }, breakpoint) => {
            await breakpoint(1000) // in ms
            const sourceSortKey = values.filters.groups[index].sort_key
            const valueForSourceCondition = sourceSortKey ? values.affectedUsers[sourceSortKey] : undefined
            const newGroup = values.filters.groups[values.filters.groups.length - 1]
            actions.setAffectedUsers(newGroup.sort_key, valueForSourceCondition)
        },
        updateConditionSet: async ({ index, newProperties }, breakpoint) => {
            const group: FeatureFlagGroupTypeWithSortKey | undefined = values.filters.groups[index]
            if (!group) {
                console.warn('Tried to update condition set at invalid index', index)
                return
            }

            const { sort_key: sortKey } = group

            if (newProperties) {
                // properties have changed, so we'll have to re-fetch affected users
                actions.setAffectedUsers(sortKey, undefined)

                // Add any new flag IDs from the updated properties
                const newFlagIds = newProperties.flatMap((property) =>
                    property.type === PropertyFilterType.Flag && property.key ? [property.key] : []
                )

                const allFlagIds = [...values.flagIds, ...newFlagIds]
                if (allFlagIds.length > 0) {
                    await actions.loadAllFlagKeys(allFlagIds)
                }
            }

            if (!newProperties || newProperties.some(isEmptyProperty)) {
                return
            }

            await breakpoint(1000) // in ms
            const response = await api.create(
                `api/projects/${values.currentProjectId}/feature_flags/user_blast_radius`,
                {
                    condition: { properties: newProperties },
                    group_type_index: values.filters?.aggregation_group_type_index ?? null,
                }
            )

            actions.setAffectedUsers(sortKey, response.users_affected)
            actions.setTotalUsers(response.total_users)
        },
        addConditionSet: () => {
            const newGroup = values.filters.groups[values.filters.groups.length - 1]
            if (newGroup.sort_key) {
                actions.setAffectedUsers(newGroup.sort_key, values.totalUsers || -1)
            }
        },
        setAggregationGroupTypeIndex: () => {
            actions.calculateBlastRadius()
        },
        calculateBlastRadius: async () => {
            const usersAffectedPromises: Promise<{ result: UserBlastRadiusType; sortKey: string }>[] = []

            values.filters.groups.forEach((condition: FeatureFlagGroupTypeWithSortKey) => {
                const { sort_key: sortKey } = condition
                actions.setAffectedUsers(sortKey, undefined)

                const properties = condition.properties
                let responsePromise: Promise<UserBlastRadiusType>
                if (!properties || properties.some(isEmptyProperty)) {
                    // don't compute for incomplete conditions
                    responsePromise = Promise.resolve({ users_affected: -1, total_users: -1 })
                } else if (properties.length === 0) {
                    // Request total users for empty condition sets
                    responsePromise = api.create(
                        `api/projects/${values.currentProjectId}/feature_flags/user_blast_radius`,
                        {
                            condition: { properties: [] },
                            group_type_index: values.filters?.aggregation_group_type_index ?? null,
                        }
                    )
                } else {
                    responsePromise = api.create(
                        `api/projects/${values.currentProjectId}/feature_flags/user_blast_radius`,
                        {
                            condition,
                            group_type_index: values.filters?.aggregation_group_type_index ?? null,
                        }
                    )
                }
                usersAffectedPromises.push(responsePromise.then((result) => ({ result, sortKey })))
            })

            const results = await Promise.all(usersAffectedPromises)

            results.forEach(({ result, sortKey }) => {
                actions.setAffectedUsers(sortKey, result.users_affected)
                if (result.total_users !== -1) {
                    actions.setTotalUsers(result.total_users)
                }
            })
        },
        loadAllFlagKeys: async ({ flagIds }) => {
            if (!flagIds || flagIds.length === 0) {
                return
            }

            // Remove duplicates
            const uniqueFlagIds = [...new Set(flagIds)]

            // Filter out IDs that are already cached
            const uncachedIds = uniqueFlagIds.filter((id: string) => !values.flagKeyCache[id])
            if (uncachedIds.length === 0) {
                return
            }

            // Set loading state
            actions.setFlagKeysLoading(true)

            try {
                const validIds = uncachedIds
                    .map((id: string) => {
                        const parsed = parseInt(id, 10)
                        if (!isNaN(parsed)) {
                            return parsed
                        }
                        // This should pretty much never happen, but we'll log it just in case
                        console.warn(`Non-numeric flag ID detected and skipped: "${id}"`)
                        return null
                    })
                    .filter((id): id is number => id !== null)

                if (validIds.length === 0) {
                    actions.setFlagKeysLoading(false)
                    return
                }

                const response = await api.featureFlags.bulkKeys(validIds)
                const keys = response.keys

                // Create a mapping with all returned keys
                const flagKeyMapping: Record<string, string> = {}

                // Add all returned keys to the mapping
                Object.entries(keys).forEach(([id, key]) => {
                    flagKeyMapping[id] = key
                })
                // For any IDs that weren't returned (not found), use the ID as fallback
                uncachedIds.forEach((id: string) => {
                    if (!keys[id]) {
                        // This should rarely happen.
                        console.warn(`Flag with ID ${id} not found. Using ID as fallback key.`)
                        flagKeyMapping[id] = id
                    }
                })

                // Update the entire cache at once
                actions.setFlagKeys(flagKeyMapping)
            } catch (error) {
                console.error('Error loading flag keys:', error)
                // Fall back to using IDs as keys
                const fallbackMapping: Record<string, string> = {}
                uncachedIds.forEach((id: string) => {
                    fallbackMapping[id] = id
                })
                actions.setFlagKeys(fallbackMapping)
            } finally {
                // Clear loading state
                actions.setFlagKeysLoading(false)
            }
        },
    })),
    selectors({
        // Get the appropriate groups based on isSuper
        filterGroups: [
            (s) => [s.filters, (_, props) => props.isSuper],
            (filters: FeatureFlagFilters, isSuper: boolean) => (isSuper ? filters.super_groups : filters.groups) || [],
        ],
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
                    targetGroupTypes.push(TaxonomicFilterGroupType.FeatureFlags)
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
                        rollout_percentage === undefined || rollout_percentage === null
                            ? 'You need to set a rollout % value'
                            : isNaN(Number(rollout_percentage))
                              ? 'Rollout percentage must be a valid number'
                              : rollout_percentage < 0 || rollout_percentage > 100
                                ? 'Rollout percentage must be between 0 and 100'
                                : undefined,
                    variant: null,
                }))
            },
        ],
        computeBlastRadiusPercentage: [
            (s) => [s.affectedUsers, s.totalUsers],
            (affectedUsers, totalUsers) => (rolloutPercentage, sortKey) => {
                let effectiveRolloutPercentage = rolloutPercentage
                if (
                    rolloutPercentage === undefined ||
                    rolloutPercentage === null ||
                    (rolloutPercentage && rolloutPercentage > 100)
                ) {
                    effectiveRolloutPercentage = 100
                }

                if (
                    affectedUsers[sortKey] === -1 ||
                    totalUsers === -1 ||
                    !totalUsers ||
                    affectedUsers[sortKey] === undefined
                ) {
                    return effectiveRolloutPercentage
                }

                let effectiveTotalUsers = totalUsers
                if (effectiveTotalUsers === 0) {
                    effectiveTotalUsers = 1
                }

                return (
                    Math.round(
                        effectiveRolloutPercentage * ((affectedUsers[sortKey] ?? 0) / effectiveTotalUsers) * 1000000
                    ) / 1000000
                )
            },
        ],
        getFlagKey: [
            (s) => [s.flagKeyCache],
            (flagKeyCache) => (flagId: string) => {
                return flagKeyCache[flagId] || flagId
            },
        ],
        flagKeysLoading: [(s) => [s.flagKeyLoading], (flagKeyLoading) => flagKeyLoading],
        flagIds: [
            (s) => [s.filterGroups],
            (filterGroups: FeatureFlagGroupType[]) =>
                filterGroups?.flatMap(
                    (group: FeatureFlagGroupType) =>
                        group.properties?.flatMap((property: AnyPropertyFilter) =>
                            property.type === PropertyFilterType.Flag && property.key ? [property.key] : []
                        ) || []
                ) || [],
        ],
        properties: [
            (s) => [s.filterGroups],
            (filterGroups: FeatureFlagGroupType[]) => {
                return filterGroups?.flatMap((g) => g.properties ?? []) ?? []
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
    afterMount(({ props, actions, values }) => {
        // Load flag keys on mount if there are flag dependencies
        if (props.filters) {
            const { flagIds } = values
            if (flagIds.length > 0) {
                actions.loadAllFlagKeys(flagIds)
            }
        }

        if (!props.readOnly) {
            actions.calculateBlastRadius()
        }
    }),
])
