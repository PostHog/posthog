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
import { isEmptyProperty, isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType, TaxonomicFilterProps } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils/objects'
import { isOperatorSemver } from 'lib/utils/operators'
import { isValidSemverValue } from 'lib/utils/semver'
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
    PropertyOperator,
    UserBlastRadiusType,
} from '~/types'

import { resolveAggregationGroupTypeIndex } from './aggregation'
import type { featureFlagReleaseConditionsLogicType } from './featureFlagReleaseConditionsLogicType'

// A property filter targets people by their raw distinct id.
export function isDistinctIdFilter(property: AnyPropertyFilter): boolean {
    return property.type === PropertyFilterType.Person && property.key === 'distinct_id'
}

// Gates the release-condition save on the same rules the backend enforces, so a bad value is
// surfaced inline instead of failing with an opaque 400 on submit.
function getPropertyValueError(property: AnyPropertyFilter): string | undefined {
    if (isEmptyProperty(property)) {
        return "Property filters can't be empty"
    }
    if (isPropertyFilterWithOperator(property) && isOperatorSemver(property.operator)) {
        const allowWildcard = property.operator === PropertyOperator.SemverWildcard
        if (typeof property.value !== 'string' || !isValidSemverValue(property.value, { allowWildcard })) {
            return 'Enter a valid semver value (e.g. 1.2.3)'
        }
    }
    return undefined
}

// Server caps batch_by_distinct_ids per request; chunk client-side so every id resolves.
const DISTINCT_ID_BATCH_SIZE = 200

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
    /**
     * When true, prevents blast radius API calls from being made.
     * Use this for readonly displays where live calculations aren't needed.
     * @see calculateBlastRadius listener which checks this prop
     */
    readOnly?: boolean
    onChange?: (filters: FeatureFlagFilters, errors: any) => void
    nonEmptyFeatureFlagVariants?: MultivariateFlagVariant[]
    evaluationRuntime?: FeatureFlagEvaluationRuntime
}

export type FeatureFlagGroupTypeWithSortKey = FeatureFlagGroupType & {
    sort_key: string
}

function ensureSortKeys(
    filters: FeatureFlagFilters
): FeatureFlagFilters & { groups: FeatureFlagGroupTypeWithSortKey[] } {
    return {
        ...filters,
        groups: (filters.groups ?? []).map((group: FeatureFlagGroupType) => ({
            ...group,
            sort_key: group.sort_key ?? uuidv4(),
        })),
    }
}

export const featureFlagReleaseConditionsLogic = kea<featureFlagReleaseConditionsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagReleaseConditionsLogic']),
    props({} as FeatureFlagReleaseConditionsLogicProps),
    key(({ id }) => id ?? 'unknown'),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], groupsModel, ['groupTypes', 'aggregationLabel']],
    })),
    actions({
        setFilters: (filters: FeatureFlagFilters) => ({ filters }),
        setAggregationGroupTypeIndex: (value: number | null) => ({ value }),
        addConditionSet: (sortKey?: string) => ({ sortKey }),
        removeConditionSet: (index: number) => ({ index }),
        duplicateConditionSet: (index: number) => ({ index }),
        moveConditionSetUp: (index: number) => ({ index }),
        moveConditionSetDown: (index: number) => ({ index }),
        reorderConditionSets: (activeId: string, overId: string) => ({ activeId, overId }),
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
        setEarlyExit: (earlyExit: boolean) => ({ earlyExit }),
        setConditionAggregation: (index: number, groupTypeIndex: number | null) => ({
            index,
            groupTypeIndex,
        }),
        setAffectedCount: (sortKey: string, count?: number) => ({
            sortKey,
            count,
        }),
        setTotalCount: (sortKey: string, count?: number) => ({
            sortKey,
            count,
        }),
        calculateBlastRadius: true,
        calculateBlastRadiusForCondition: (
            sortKey: string,
            properties: AnyPropertyFilter[] | undefined,
            groupTypeIndex: number | null
        ) => ({
            sortKey,
            properties,
            groupTypeIndex,
        }),
        loadAllFlagKeys: (flagIds: string[]) => ({ flagIds }),
        setFlagKeys: (flagKeys: Record<string, string>) => ({ flagKeys }),
        setFlagKeysLoading: (isLoading: boolean) => ({ isLoading }),
        loadDistinctIdNames: (distinctIds: string[]) => ({ distinctIds }),
        setDistinctIdNames: (distinctIdNames: Record<string, string>) => ({ distinctIdNames }),
        setOpenConditions: (openConditions: string[]) => ({ openConditions }),
        openCondition: (sortKey: string) => ({ sortKey }),
        setIsAnyItemDragging: (isAnyItemDragging: boolean) => ({ isAnyItemDragging }),
        setDraggedGroup: (draggedGroup: FeatureFlagGroupType | null) => ({ draggedGroup }),
    }),
    defaults(({ props }) => ({
        filters: ensureSortKeys(props.filters),
    })),
    reducers(() => ({
        filters: {
            setFilters: (state, { filters }) => {
                // Preserve sort_keys from previous state when possible
                const groupsWithKeys = (filters.groups ?? []).map(
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
                if (!state) {
                    return state
                }

                const globalUnchanged = state.aggregation_group_type_index == value
                const hasPerConditionAggregations = state.groups.some((g) => g.aggregation_group_type_index != null)

                if (globalUnchanged && !hasPerConditionAggregations) {
                    return state
                }

                // Coming from mixed mode: selectively preserve conditions whose
                // aggregation scope matches the new target
                if (hasPerConditionAggregations) {
                    return {
                        ...state,
                        aggregation_group_type_index: value,
                        groups: state.groups.map((group) => {
                            const previousEffective = resolveAggregationGroupTypeIndex(
                                group.aggregation_group_type_index,
                                state.aggregation_group_type_index
                            )
                            // Use == to treat null and undefined equivalently
                            const scopeChanged = previousEffective != value
                            return {
                                ...group,
                                aggregation_group_type_index: undefined,
                                properties: scopeChanged ? [] : group.properties,
                            }
                        }) as FeatureFlagGroupTypeWithSortKey[],
                    }
                }

                // Direct transition between incompatible types (user ↔ group):
                // full reset since property filters from one scope don't apply to another
                const originalRolloutPercentage = state.groups[0]?.rollout_percentage
                return {
                    ...state,
                    aggregation_group_type_index: value,
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: originalRolloutPercentage,
                            variant: null,
                            sort_key: uuidv4(),
                        } as FeatureFlagGroupTypeWithSortKey,
                    ],
                }
            },
            addConditionSet: (state, { sortKey }) => {
                if (!state) {
                    return state
                }
                const groups = [
                    ...(state?.groups || []),
                    {
                        properties: [],
                        rollout_percentage: 0,
                        variant: null,
                        sort_key: sortKey ?? uuidv4(),
                    },
                ]
                return { ...state, groups }
            },
            updateConditionSet: (state, { index, newRolloutPercentage, newProperties, newVariant, newDescription }) => {
                if (!state) {
                    return state
                }

                const groups = [...(state?.groups || [])]
                if (newRolloutPercentage !== undefined) {
                    groups[index] = {
                        ...groups[index],
                        rollout_percentage: newRolloutPercentage,
                    }
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
            setEarlyExit: (state, { earlyExit }) => {
                if (!state) {
                    return state
                }
                return { ...state, early_exit: earlyExit }
            },
            setConditionAggregation: (state, { index, groupTypeIndex }) => {
                if (!state) {
                    return state
                }
                const groups = [...state.groups]
                groups[index] = {
                    ...groups[index],
                    aggregation_group_type_index: groupTypeIndex,
                    // Reset properties when changing aggregation type to avoid
                    // stale property filters from the previous aggregation scope
                    properties: [],
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
                return {
                    ...state,
                    groups: moveConditionSet(state.groups, index, index + 1),
                }
            },
            moveConditionSetUp: (state, { index }) => {
                if (!state || index <= 0) {
                    return state
                }
                return {
                    ...state,
                    groups: moveConditionSet(state.groups, index, index - 1),
                }
            },
            reorderConditionSets: (state, { activeId, overId }) => {
                if (!state || activeId === overId) {
                    return state
                }

                const activeIndex = state.groups.findIndex((group) => group.sort_key === activeId)
                const overIndex = state.groups.findIndex((group) => group.sort_key === overId)

                if (activeIndex === -1 || overIndex === -1) {
                    return state
                }

                return {
                    ...state,
                    groups: moveConditionSet(state.groups, activeIndex, overIndex),
                }
            },
        },
        affectedCounts: [
            {} as Record<string, number | undefined>,
            {
                setAffectedCount: (state, { sortKey, count }) => ({
                    ...state,
                    [sortKey]: count,
                }),
            },
        ],
        totalCounts: [
            {} as Record<string, number | undefined>,
            {
                setTotalCount: (state, { sortKey, count }) => ({
                    ...state,
                    [sortKey]: count,
                }),
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
        distinctIdNameCache: [
            {} as Record<string, string>,
            {
                setDistinctIdNames: (state, { distinctIdNames }) => ({
                    ...state,
                    ...distinctIdNames,
                }),
            },
        ],
        openConditions: [
            [] as string[],
            {
                setOpenConditions: (_, { openConditions }) => openConditions,
                openCondition: (state, { sortKey }) =>
                    state.includes(`condition-${sortKey}`) ? state : [...state, `condition-${sortKey}`],
            },
        ],
        isAnyItemDragging: [
            false as boolean,
            {
                setIsAnyItemDragging: (_, { isAnyItemDragging }) => isAnyItemDragging,
            },
        ],
        draggedGroup: [
            null as FeatureFlagGroupType | null,
            {
                setDraggedGroup: (_, { draggedGroup }) => draggedGroup,
            },
        ],
    })),
    listeners(({ actions, values, props }) => ({
        setFilters: async () => {
            const { flagIds, distinctIds } = values
            if (flagIds.length > 0) {
                await actions.loadAllFlagKeys(flagIds)
            }
            if (distinctIds.length > 0) {
                actions.loadDistinctIdNames(distinctIds)
            }
            // Recalculate blast radius when filters change (e.g., from template application)
            if (!props.readOnly) {
                actions.calculateBlastRadius()
            }
        },
        duplicateConditionSet: async ({ index }, breakpoint) => {
            const newGroup = values.filters.groups[values.filters.groups.length - 1]
            if (newGroup?.sort_key) {
                actions.openCondition(newGroup.sort_key)
            }
            await breakpoint(1000) // in ms
            const sourceSortKey = values.filters.groups[index]?.sort_key
            const valueForSourceCondition = sourceSortKey ? values.affectedCounts[sourceSortKey] : undefined
            actions.setAffectedCount(newGroup.sort_key, valueForSourceCondition)
        },
        updateConditionSet: async ({ index, newProperties }, breakpoint) => {
            const group: FeatureFlagGroupTypeWithSortKey | undefined = values.filters.groups[index]
            if (!group) {
                console.warn('Tried to update condition set at invalid index', index)
                return
            }

            const { sort_key: sortKey } = group

            if (newProperties) {
                // properties have changed, so we'll have to re-fetch affected counts
                actions.setAffectedCount(sortKey, undefined)
                actions.setTotalCount(sortKey, undefined)

                // Add any new flag IDs from the updated properties
                const newFlagIds = newProperties.flatMap((property) =>
                    property.type === PropertyFilterType.Flag && property.key ? [property.key] : []
                )

                const allFlagIds = [...values.flagIds, ...newFlagIds]
                if (allFlagIds.length > 0) {
                    await actions.loadAllFlagKeys(allFlagIds)
                }

                // Resolve display names for any distinct_id targeting in the updated properties.
                if (values.distinctIds.length > 0) {
                    actions.loadDistinctIdNames(values.distinctIds)
                }
            }

            if (!newProperties || newProperties.some(isEmptyProperty)) {
                return
            }

            await breakpoint(1000) // in ms
            const groupTypeIndex = resolveAggregationGroupTypeIndex(
                group.aggregation_group_type_index,
                values.filters?.aggregation_group_type_index
            )
            const response: UserBlastRadiusType = await api.create(
                `api/projects/${values.currentProjectId}/feature_flags/user_blast_radius`,
                {
                    condition: { properties: newProperties },
                    group_type_index: groupTypeIndex,
                }
            )

            actions.setAffectedCount(sortKey, response.affected)
            actions.setTotalCount(sortKey, response.total)
        },
        setConditionAggregation: ({ index }) => {
            const group = values.filters.groups[index]
            if (group?.sort_key) {
                const groupTypeIndex = resolveAggregationGroupTypeIndex(
                    group.aggregation_group_type_index,
                    values.filters?.aggregation_group_type_index
                )
                actions.calculateBlastRadiusForCondition(group.sort_key, group.properties, groupTypeIndex)
            }
        },
        addConditionSet: async () => {
            const newGroup = values.filters.groups[values.filters.groups.length - 1]
            if (newGroup.sort_key) {
                actions.openCondition(newGroup.sort_key)
                const groupTypeIndex = resolveAggregationGroupTypeIndex(
                    newGroup.aggregation_group_type_index,
                    values.filters?.aggregation_group_type_index
                )
                actions.calculateBlastRadiusForCondition(newGroup.sort_key, newGroup.properties, groupTypeIndex)
            }
        },
        removeConditionSet: () => {
            // Clean up openConditions to only include keys that still exist in groups
            const currentSortKeys = new Set(values.filters.groups.map((g) => g.sort_key))
            const newOpenConditions = values.openConditions.filter((key) => {
                const sortKey = key.replace('condition-', '')
                return currentSortKeys.has(sortKey)
            })
            if (newOpenConditions.length !== values.openConditions.length) {
                actions.setOpenConditions(newOpenConditions)
            }
        },
        setAggregationGroupTypeIndex: () => {
            actions.calculateBlastRadius()

            // Clean up stale open conditions
            const currentSortKeys = new Set(values.filters.groups.map((g) => g.sort_key))
            const newOpenConditions = values.openConditions.filter((key) => {
                const sortKey = key.replace('condition-', '')
                return currentSortKeys.has(sortKey)
            })

            // If all conditions became stale but we had some open, open the first one
            if (
                newOpenConditions.length === 0 &&
                values.openConditions.length > 0 &&
                values.filters.groups.length > 0
            ) {
                actions.setOpenConditions([`condition-${values.filters.groups[0].sort_key}`])
            } else if (newOpenConditions.length !== values.openConditions.length) {
                actions.setOpenConditions(newOpenConditions)
            }
        },
        calculateBlastRadiusForCondition: async ({ sortKey, properties, groupTypeIndex }) => {
            actions.setAffectedCount(sortKey, undefined)
            actions.setTotalCount(sortKey, undefined)

            let response: UserBlastRadiusType
            if (!properties || properties.some(isEmptyProperty)) {
                // don't compute for incomplete conditions
                response = { affected: -1, total: -1 }
            } else {
                try {
                    response = await api.create(
                        `api/projects/${values.currentProjectId}/feature_flags/user_blast_radius`,
                        {
                            condition: { properties },
                            group_type_index: groupTypeIndex,
                        }
                    )
                } catch {
                    response = { affected: -1, total: -1 }
                }
            }

            actions.setAffectedCount(sortKey, response.affected)
            actions.setTotalCount(sortKey, response.total)
        },
        calculateBlastRadius: () => {
            values.filters.groups.forEach((condition: FeatureFlagGroupTypeWithSortKey) => {
                const groupTypeIndex = resolveAggregationGroupTypeIndex(
                    condition.aggregation_group_type_index,
                    values.filters?.aggregation_group_type_index
                )
                actions.calculateBlastRadiusForCondition(condition.sort_key, condition.properties, groupTypeIndex)
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
        loadDistinctIdNames: async ({ distinctIds }) => {
            if (!distinctIds || distinctIds.length === 0) {
                return
            }

            // Only fetch ids we haven't resolved yet. Failed lookups stay uncached so they
            // retry on a later setFilters/updateConditionSet rather than pinning to the raw id.
            const uncachedIds = [...new Set(distinctIds)].filter((id) => !(id in values.distinctIdNameCache))
            if (uncachedIds.length === 0) {
                return
            }

            // Resolve a chunk to its display-name mapping, keeping the raw id when no
            // meaningful name resolved.
            const toMapping = (
                chunk: string[],
                personsByDistinctId: Record<string, { name?: string }>
            ): Record<string, string> =>
                Object.fromEntries(
                    chunk.map((id) => {
                        const name = personsByDistinctId[id]?.name
                        return [id, name && name !== id ? name : id]
                    })
                )

            // Commit each chunk as it resolves so a later-chunk failure doesn't discard
            // already-resolved names.
            for (let i = 0; i < uncachedIds.length; i += DISTINCT_ID_BATCH_SIZE) {
                const chunk = uncachedIds.slice(i, i + DISTINCT_ID_BATCH_SIZE)
                try {
                    const personsByDistinctId = await api.persons.getByDistinctIds(chunk)
                    actions.setDistinctIdNames(toMapping(chunk, personsByDistinctId))
                } catch (error) {
                    // Leave failed ids uncached so a later setFilters/updateConditionSet retries
                    // them; getDistinctIdName already renders the raw id while unresolved.
                    console.error('Error loading distinct ID names:', error)
                }
            }
        },
    })),
    selectors({
        filterGroups: [(s) => [s.filters], (filters: FeatureFlagFilters) => filters.groups || []],
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
            (filters, aggregationLabel) =>
                (conditionGroupTypeIndex?: number | null): string => {
                    const effectiveIndex = resolveAggregationGroupTypeIndex(
                        conditionGroupTypeIndex,
                        filters.aggregation_group_type_index
                    )
                    if (effectiveIndex != null) {
                        return aggregationLabel(effectiveIndex).plural
                    }
                    return 'users'
                },
        ],
        taxonomicGroupTypesForCondition: [
            (s) => [s.filters, s.groupTypes],
            (filters, groupTypes) =>
                (conditionGroupTypeIndex: number | null | undefined): TaxonomicFilterGroupType[] => {
                    const effectiveIndex = resolveAggregationGroupTypeIndex(
                        conditionGroupTypeIndex,
                        filters?.aggregation_group_type_index
                    )
                    const targetGroupTypes: TaxonomicFilterGroupType[] = []

                    if (effectiveIndex != null) {
                        // Group-aggregated condition: only show group properties
                        // for the target group type. Condition sets are homogeneous.
                        const targetGroup = groupTypes.get(effectiveIndex as GroupTypeIndex)
                        if (targetGroup) {
                            targetGroupTypes.push(
                                `${TaxonomicFilterGroupType.GroupsPrefix}_${targetGroup.group_type_index}` as unknown as TaxonomicFilterGroupType
                            )
                            targetGroupTypes.push(
                                `${TaxonomicFilterGroupType.GroupNamesPrefix}_${effectiveIndex}` as unknown as TaxonomicFilterGroupType
                            )
                        }
                    } else {
                        // Person-aggregated condition: show person, cohort, flag, and metadata properties
                        targetGroupTypes.push(TaxonomicFilterGroupType.PersonProperties)
                        targetGroupTypes.push(TaxonomicFilterGroupType.Cohorts)
                        targetGroupTypes.push(TaxonomicFilterGroupType.FeatureFlags)
                        targetGroupTypes.push(TaxonomicFilterGroupType.Metadata)
                    }

                    return targetGroupTypes
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
                        {
                            name: 'distinct_id',
                            propertyFilterType: PropertyFilterType.Person,
                        },
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
                        value: getPropertyValueError(property),
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
            (s) => [s.affectedCounts, s.totalCounts],
            (affectedCounts, totalCounts) => (rolloutPercentage, sortKey) => {
                let effectiveRolloutPercentage = rolloutPercentage
                if (
                    rolloutPercentage === undefined ||
                    rolloutPercentage === null ||
                    (rolloutPercentage && rolloutPercentage > 100)
                ) {
                    effectiveRolloutPercentage = 100
                }

                const affected = affectedCounts[sortKey]
                const total = totalCounts[sortKey]

                if (affected === -1 || total === -1 || !total || affected === undefined) {
                    return effectiveRolloutPercentage
                }

                let effectiveTotal = total
                if (effectiveTotal === 0) {
                    effectiveTotal = 1
                }

                return Math.round(effectiveRolloutPercentage * ((affected ?? 0) / effectiveTotal) * 1000000) / 1000000
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
        distinctIds: [
            (s) => [s.filterGroups],
            (filterGroups: FeatureFlagGroupType[]): string[] =>
                filterGroups?.flatMap(
                    (group: FeatureFlagGroupType) =>
                        group.properties?.flatMap((property: AnyPropertyFilter) => {
                            if (!isDistinctIdFilter(property)) {
                                return []
                            }
                            if (Array.isArray(property.value)) {
                                return property.value.map((v) => String(v))
                            }
                            return property.value !== null && property.value !== undefined
                                ? [String(property.value)]
                                : []
                        }) || []
                ) || [],
        ],
        getDistinctIdName: [
            (s) => [s.distinctIdNameCache],
            (distinctIdNameCache: Record<string, string>) =>
                (distinctId: string): string => {
                    const name = distinctIdNameCache[distinctId]
                    return name && name !== distinctId ? `${distinctId} (${name})` : distinctId
                },
        ],
        properties: [
            (s) => [s.filterGroups],
            (filterGroups: FeatureFlagGroupType[]) => {
                return filterGroups?.flatMap((g) => g.properties ?? []) ?? []
            },
        ],
    }),
    propsChanged(({ props, values, actions }) => {
        // Compare only the fields that affect release conditions and blast radius,
        // excluding payloads which don't affect targeting
        const { payloads: _newPayloads, ...newRelevant } = props.filters
        const { payloads: _oldPayloads, ...oldRelevant } = values.filters
        if (!objectsEqual(newRelevant, oldRelevant)) {
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
            const { flagIds, distinctIds } = values
            if (flagIds.length > 0) {
                actions.loadAllFlagKeys(flagIds)
            }
            if (distinctIds.length > 0) {
                actions.loadDistinctIdNames(distinctIds)
            }
        }

        if (!props.readOnly) {
            actions.calculateBlastRadius()
        }

        // Initialize first condition as open if there's only one
        if (values.filters.groups.length === 1 && values.filters.groups[0]?.sort_key) {
            actions.setOpenConditions([`condition-${values.filters.groups[0].sort_key}`])
        }
    }),
])
