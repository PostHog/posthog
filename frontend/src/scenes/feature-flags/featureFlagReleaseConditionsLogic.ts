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
import { objectsEqual, range } from 'lib/utils'
import { projectLogic } from 'scenes/projectLogic'

import { groupsModel } from '~/models/groupsModel'
import {
    AnyPropertyFilter,
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

// Helper function to swap affected users between two indices
function swapAffectedUsers(
    affectedUsers: Record<number, number | undefined>,
    actions: { setAffectedUsers: (index: number, count?: number) => void },
    fromIndex: number,
    toIndex: number
): void {
    if (!(fromIndex in affectedUsers) || !(toIndex in affectedUsers)) {
        return
    }

    const fromCount = affectedUsers[fromIndex]
    const toCount = affectedUsers[toIndex]
    actions.setAffectedUsers(toIndex, fromCount)
    actions.setAffectedUsers(fromIndex, toCount)
}

// TODO: Type onChange errors properly
export interface FeatureFlagReleaseConditionsLogicProps {
    filters: FeatureFlagFilters
    id?: string
    readOnly?: boolean
    onChange?: (filters: FeatureFlagFilters, errors: any) => void
    nonEmptyFeatureFlagVariants?: MultivariateFlagVariant[]
    isSuper?: boolean
}

function ensureSortKeys(filters: FeatureFlagFilters): FeatureFlagFilters {
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
        setAffectedUsers: (index: number, count?: number) => ({ index, count }),
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
            setFilters: (_, { filters }) => {
                // Only assign sort_keys to groups that don't have one
                const groupsWithKeys = filters.groups.map((group: FeatureFlagGroupType) => {
                    if (group.sort_key) {
                        return group
                    }
                    return {
                        ...group,
                        sort_key: uuidv4(),
                    }
                })

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
                const groups = state.groups.concat([
                    {
                        ...state.groups[index],
                        sort_key: uuidv4(),
                    },
                ])
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
            const valueForSourceCondition = values.affectedUsers[index]
            const newIndex = values.filters.groups.length - 1
            actions.setAffectedUsers(newIndex, valueForSourceCondition)
        },
        updateConditionSet: async ({ index, newProperties }, breakpoint) => {
            if (newProperties) {
                // properties have changed, so we'll have to re-fetch affected users
                actions.setAffectedUsers(index, undefined)

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
            actions.setAffectedUsers(index, response.users_affected)
            actions.setTotalUsers(response.total_users)
        },
        addConditionSet: () => {
            actions.setAffectedUsers(values.filters.groups.length - 1, values.totalUsers || -1)
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
                if (!properties || properties.some(isEmptyProperty)) {
                    // don't compute for incomplete conditions
                    usersAffected.push(Promise.resolve({ users_affected: -1, total_users: -1 }))
                } else if (properties.length === 0) {
                    // Request total users for empty condition sets
                    const responsePromise = api.create(
                        `api/projects/${values.currentProjectId}/feature_flags/user_blast_radius`,
                        {
                            condition: { properties: [] },
                            group_type_index: values.filters?.aggregation_group_type_index ?? null,
                        }
                    )

                    usersAffected.push(responsePromise)
                } else {
                    const responsePromise = api.create(
                        `api/projects/${values.currentProjectId}/feature_flags/user_blast_radius`,
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
        moveConditionSetUp: ({ index }) => {
            swapAffectedUsers(values.affectedUsers, actions, index, index - 1)
        },
        moveConditionSetDown: ({ index }) => {
            swapAffectedUsers(values.affectedUsers, actions, index, index + 1)
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
