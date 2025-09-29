import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { v4 as uuidv4 } from 'uuid'

import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils'
import { projectLogic } from 'scenes/projectLogic'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter, FeatureFlagFilters, FeatureFlagGroupType, UserBlastRadiusType } from '~/types'

import type { targetingPanelLogicType } from './targetingPanelLogicType'

export interface TargetingPanelLogicProps {
    filters: FeatureFlagFilters
    id?: string
    readOnly?: boolean
    onChange?: (filters: FeatureFlagFilters) => void
}

function ensureSortKeys(filters: FeatureFlagFilters): FeatureFlagFilters {
    return {
        ...filters,
        groups: (filters.groups || []).map((group: FeatureFlagGroupType) => ({
            ...group,
            sort_key: group.sort_key ?? uuidv4(),
        })),
    }
}

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

export const targetingPanelLogic = kea<targetingPanelLogicType>([
    path(['scenes', 'experiments', 'create', 'panels', 'targetingPanelLogic']),
    props({} as TargetingPanelLogicProps),
    key(({ id }) => id ?? 'new'),
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
            newDescription?: string | null
        ) => ({
            index,
            newRolloutPercentage,
            newProperties,
            newDescription,
        }),
        setAffectedUsers: (index: number, count?: number) => ({ index, count }),
        setTotalUsers: (count: number) => ({ count }),
        calculateBlastRadius: true,
    }),
    reducers(({ props }) => ({
        filters: [
            ensureSortKeys(props.filters || { groups: [], aggregation_group_type_index: null }),
            {
                setFilters: (_, { filters }) => {
                    // Only assign sort_keys to groups that don't have one
                    const groupsWithKeys = (filters.groups || []).map((group: FeatureFlagGroupType) => {
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
                    if (!state || state.aggregation_group_type_index === value) {
                        return state
                    }

                    const originalRolloutPercentage = state.groups?.[0]?.rollout_percentage ?? 100

                    return {
                        ...state,
                        aggregation_group_type_index: value,
                        // Reset property filters after changing what you're aggregating by
                        groups: [
                            {
                                variant: null,
                                properties: [],
                                rollout_percentage: originalRolloutPercentage,
                                sort_key: uuidv4(),
                            },
                        ],
                    }
                },
                addConditionSet: (state) => {
                    if (!state) {
                        return state
                    }
                    const groups = [...state.groups]
                    groups.push({
                        properties: [],
                        rollout_percentage: 100,
                        variant: null,
                        sort_key: uuidv4(),
                    })

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
                    const groups = [...state.groups]
                    const groupToDuplicate = { ...groups[index], sort_key: uuidv4() }
                    groups.splice(index + 1, 0, groupToDuplicate)

                    return { ...state, groups }
                },
                moveConditionSetUp: (state, { index }) => {
                    if (!state || index <= 0) {
                        return state
                    }
                    return { ...state, groups: moveConditionSet(state.groups, index, index - 1) }
                },
                moveConditionSetDown: (state, { index }) => {
                    if (!state || index >= state.groups.length - 1) {
                        return state
                    }
                    return { ...state, groups: moveConditionSet(state.groups, index, index + 1) }
                },
                updateConditionSet: (state, { index, newRolloutPercentage, newProperties, newDescription }) => {
                    if (!state) {
                        return state
                    }
                    const groups = [...state.groups]
                    if (newRolloutPercentage !== undefined) {
                        groups[index] = { ...groups[index], rollout_percentage: newRolloutPercentage }
                    }
                    if (newProperties !== undefined) {
                        groups[index] = { ...groups[index], properties: newProperties }
                    }
                    if (newDescription !== undefined) {
                        groups[index] = { ...groups[index], description: newDescription || null }
                    }

                    return { ...state, groups }
                },
            },
        ],
        affectedUsers: [
            {} as Record<number, number | undefined>,
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
    listeners(({ actions, values, props }) => ({
        setFilters: () => {
            props.onChange?.(values.filters)
        },
        setAggregationGroupTypeIndex: () => {
            props.onChange?.(values.filters)
        },
        addConditionSet: () => {
            props.onChange?.(values.filters)
        },
        removeConditionSet: () => {
            props.onChange?.(values.filters)
        },
        duplicateConditionSet: () => {
            props.onChange?.(values.filters)
        },
        updateConditionSet: () => {
            props.onChange?.(values.filters)
        },
        moveConditionSetUp: ({ index }) => {
            swapAffectedUsers(values.affectedUsers, actions, index, index - 1)
            props.onChange?.(values.filters)
        },
        moveConditionSetDown: ({ index }) => {
            swapAffectedUsers(values.affectedUsers, actions, index, index + 1)
            props.onChange?.(values.filters)
        },
        calculateBlastRadius: async () => {
            const { filters } = values
            const projectId = values.currentProjectId

            if (!projectId || !filters?.groups?.length) {
                return
            }

            // Clear existing affected users
            filters.groups.forEach((_, index) => {
                actions.setAffectedUsers(index, undefined)
            })

            try {
                const response = await api.create(`api/projects/${projectId}/feature_flags/user_blast_radius`, {
                    filters,
                    aggregation_group_type_index: filters.aggregation_group_type_index ?? null,
                })

                const result = response as UserBlastRadiusType

                if (result.users_affected && result.total_users) {
                    actions.setTotalUsers(result.total_users)
                    if (Array.isArray(result.users_affected)) {
                        result.users_affected.forEach((count: number, index: number) => {
                            actions.setAffectedUsers(index, count)
                        })
                    }
                }
            } catch (error) {
                console.error('Failed to calculate blast radius:', error)
            }
        },
    })),
    selectors({
        aggregationTargetName: [
            (s) => [s.filters],
            (filters): string => {
                if (filters.aggregation_group_type_index != null) {
                    return 'groups'
                }
                return 'users'
            },
        ],
        taxonomicGroupTypes: [
            (s) => [s.filters],
            (filters): TaxonomicFilterGroupType[] => {
                if (filters.aggregation_group_type_index != null) {
                    return [
                        TaxonomicFilterGroupType.CohortsWithAllUsers,
                        TaxonomicFilterGroupType.FeatureFlags,
                        `${TaxonomicFilterGroupType.GroupsPrefix}_${filters.aggregation_group_type_index}` as TaxonomicFilterGroupType,
                        TaxonomicFilterGroupType.Actions,
                        TaxonomicFilterGroupType.Events,
                    ]
                }

                return [
                    TaxonomicFilterGroupType.CohortsWithAllUsers,
                    TaxonomicFilterGroupType.FeatureFlags,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.Events,
                ]
            },
        ],
        computeBlastRadiusPercentage: [
            (s) => [s.affectedUsers, s.totalUsers],
            (affectedUsers, totalUsers) => {
                return (rolloutPercentage: number | null | undefined, index: number): number => {
                    if (
                        totalUsers === null ||
                        totalUsers === undefined ||
                        affectedUsers[index] === undefined ||
                        totalUsers === 0
                    ) {
                        return 0
                    }
                    const rollout = rolloutPercentage ?? 100
                    return ((affectedUsers[index] || 0) / totalUsers) * (rollout / 100) * 100
                }
            },
        ],
    }),
    subscriptions(({ actions }) => ({
        filters: (filters, oldFilters) => {
            if (!objectsEqual(filters, oldFilters)) {
                actions.calculateBlastRadius()
            }
        },
    })),
])
