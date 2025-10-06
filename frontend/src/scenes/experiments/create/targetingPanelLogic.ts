import { actions, afterMount, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { v4 as uuidv4 } from 'uuid'

import api from 'lib/api'
import { isEmptyProperty } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual, range } from 'lib/utils'
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
    defaults(({ props }) => ({
        filters: ensureSortKeys(props.filters || { groups: [], aggregation_group_type_index: null }),
    })),
    reducers(() => ({
        filters: {
            setFilters: (_, { filters }) => {
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

                const originalRolloutPercentage = state.groups?.[0]?.rollout_percentage

                return {
                    ...state,
                    aggregation_group_type_index: value,
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
                const groups = [
                    ...(state.groups || []),
                    { properties: [], rollout_percentage: 100, variant: null, sort_key: uuidv4() },
                ]
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
                const groups = [...(state.groups || [])]
                if (newRolloutPercentage !== undefined) {
                    groups[index] = { ...groups[index], rollout_percentage: newRolloutPercentage }
                }
                if (newProperties !== undefined) {
                    groups[index] = { ...groups[index], properties: newProperties }
                }
                if (newDescription !== undefined) {
                    const description = newDescription && newDescription.trim() ? newDescription : null
                    groups[index] = { ...groups[index], description }
                }

                return { ...state, groups }
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
    })),
    listeners(({ actions, values, props }) => ({
        setFilters: () => {
            props.onChange?.(values.filters)
        },
        setAggregationGroupTypeIndex: () => {
            props.onChange?.(values.filters)
            actions.calculateBlastRadius()
        },
        addConditionSet: () => {
            actions.setAffectedUsers(values.filters.groups.length - 1, values.totalUsers || -1)
            props.onChange?.(values.filters)
        },
        removeConditionSet: ({ index }) => {
            const previousLength = Object.keys(values.affectedUsers).length
            range(index, previousLength).forEach((idx) => {
                const count = previousLength - 1 === idx ? undefined : values.affectedUsers[idx + 1]
                actions.setAffectedUsers(idx, count)
            })
            props.onChange?.(values.filters)
        },
        duplicateConditionSet: async ({ index }, breakpoint) => {
            await breakpoint(1000)
            const valueForSourceCondition = values.affectedUsers[index]
            const newIndex = values.filters.groups.length - 1
            actions.setAffectedUsers(newIndex, valueForSourceCondition)
            props.onChange?.(values.filters)
        },
        updateConditionSet: async ({ index, newProperties }, breakpoint) => {
            if (newProperties) {
                actions.setAffectedUsers(index, undefined)
            }

            if (!newProperties || newProperties.some(isEmptyProperty)) {
                props.onChange?.(values.filters)
                return
            }

            await breakpoint(1000)
            const response = await api.create(
                `api/projects/${values.currentProjectId}/feature_flags/user_blast_radius`,
                {
                    condition: { properties: newProperties },
                    group_type_index: values.filters?.aggregation_group_type_index ?? null,
                }
            )
            actions.setAffectedUsers(index, response.users_affected)
            actions.setTotalUsers(response.total_users)
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
            const usersAffected: Promise<UserBlastRadiusType>[] = []

            values.filters?.groups?.forEach((condition, index) => {
                actions.setAffectedUsers(index, undefined)

                const properties = condition.properties
                if (!properties || properties.some(isEmptyProperty)) {
                    usersAffected.push(Promise.resolve({ users_affected: -1, total_users: -1 }))
                } else if (properties.length === 0) {
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
            results.forEach((result, index) => {
                actions.setAffectedUsers(index, result.users_affected)
                if (result.total_users !== -1) {
                    actions.setTotalUsers(result.total_users)
                }
            })
        },
    })),
    selectors({
        aggregationTargetName: [
            (s) => [s.filters, s.aggregationLabel],
            (
                filters: FeatureFlagFilters,
                aggregationLabel: (index: number) => { singular: string; plural: string }
            ): string => {
                if (filters.aggregation_group_type_index != null) {
                    return aggregationLabel(filters.aggregation_group_type_index).plural
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
                    let effectiveRolloutPercentage: number = rolloutPercentage ?? 100
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
                }
            },
        ],
    }),
    subscriptions(({ props }) => ({
        filters: (value, oldValue) => {
            if (!objectsEqual(value, oldValue)) {
                props.onChange?.(value)
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (!props.readOnly) {
            actions.calculateBlastRadius()
        }
    }),
])
