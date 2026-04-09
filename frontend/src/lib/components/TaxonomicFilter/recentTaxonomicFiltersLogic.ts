import { actions, kea, path, reducers, selectors } from 'kea'

import { now } from 'lib/dayjs'
import { isOperatorFlag } from 'lib/utils'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { AnyPropertyFilter } from '~/types'

import type { recentTaxonomicFiltersLogicType } from './recentTaxonomicFiltersLogicType'
import { META_GROUP_TYPES, TaxonomicDefinitionTypes, TaxonomicFilterGroupType, TaxonomicFilterValue } from './types'

export const MAX_RECENT_FILTERS = 20
export const RECENT_FILTER_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000
const EXCLUDED_RECENT_FILTER_GROUP_TYPES = new Set<TaxonomicFilterGroupType>([
    ...META_GROUP_TYPES,
    TaxonomicFilterGroupType.DataWarehouse,
    TaxonomicFilterGroupType.DataWarehouseProperties,
    TaxonomicFilterGroupType.DataWarehousePersonProperties,
])

export interface RecentTaxonomicFilter {
    groupType: TaxonomicFilterGroupType
    groupName: string
    value: TaxonomicFilterValue
    item: Record<string, any>
    timestamp: number
    teamId?: number
    propertyFilter?: AnyPropertyFilter
}

export interface RecentItemContext {
    sourceGroupType: TaxonomicFilterGroupType
    sourceGroupName: string
    teamId?: number
    propertyFilter?: AnyPropertyFilter
}

export function hasRecentContext(item: unknown): item is Record<string, any> & { _recentContext: RecentItemContext } {
    return typeof item === 'object' && item != null && '_recentContext' in item && (item as any)._recentContext != null
}

export function stripRecentContext<T extends Record<string, any>>(item: T): Omit<T, '_recentContext'> {
    const { _recentContext: _, ...clean } = item
    return clean
}

function isCompleteRecentPropertyFilter(propertyFilter: AnyPropertyFilter | undefined): boolean {
    if (!propertyFilter) {
        return false
    }
    const hasValue =
        'value' in propertyFilter &&
        propertyFilter.value != null &&
        !(Array.isArray(propertyFilter.value) && propertyFilter.value.length === 0)
    const op = 'operator' in propertyFilter ? propertyFilter.operator : undefined
    return hasValue || (!!op && isOperatorFlag(op))
}

function isDuplicateRecentFilter(
    existing: RecentTaxonomicFilter,
    incoming: { groupType: TaxonomicFilterGroupType; value: TaxonomicFilterValue; propertyFilter?: AnyPropertyFilter }
): boolean {
    if (existing.groupType !== incoming.groupType || existing.value !== incoming.value) {
        return false
    }
    const existingComplete = isCompleteRecentPropertyFilter(existing.propertyFilter)
    const incomingComplete = isCompleteRecentPropertyFilter(incoming.propertyFilter)
    if (existingComplete !== incomingComplete) {
        return false
    }
    if (!existingComplete && !incomingComplete) {
        return true
    }
    if (existing.propertyFilter && incoming.propertyFilter) {
        const eOp = 'operator' in existing.propertyFilter ? existing.propertyFilter.operator : undefined
        const eVal = 'value' in existing.propertyFilter ? existing.propertyFilter.value : undefined
        const iOp = 'operator' in incoming.propertyFilter ? incoming.propertyFilter.operator : undefined
        const iVal = 'value' in incoming.propertyFilter ? incoming.propertyFilter.value : undefined
        return eOp === iOp && JSON.stringify(eVal) === JSON.stringify(iVal)
    }
    return true
}

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id

export const recentTaxonomicFiltersLogic = kea<recentTaxonomicFiltersLogicType>([
    path(['lib', 'components', 'TaxonomicFilter', 'recentTaxonomicFiltersLogic']),
    actions({
        recordRecentFilter: (
            groupType: TaxonomicFilterGroupType,
            groupName: string,
            value: TaxonomicFilterValue,
            item: any,
            teamId?: number,
            propertyFilter?: AnyPropertyFilter
        ) => ({
            groupType,
            groupName,
            value,
            item,
            teamId,
            propertyFilter,
        }),
        clearRecentFilters: true,
    }),
    reducers({
        recentFilters: [
            [] as RecentTaxonomicFilter[],
            { persist: true, prefix: `${teamId}__` },
            {
                clearRecentFilters: () => [],
                recordRecentFilter: (state, { groupType, groupName, value, item, teamId, propertyFilter }) => {
                    if (EXCLUDED_RECENT_FILTER_GROUP_TYPES.has(groupType) || value == null) {
                        return state
                    }

                    const incomingComplete = isCompleteRecentPropertyFilter(propertyFilter)
                    if (
                        !incomingComplete &&
                        state.some(
                            (f) =>
                                f.groupType === groupType &&
                                f.value === value &&
                                isCompleteRecentPropertyFilter(f.propertyFilter)
                        )
                    ) {
                        return state
                    }

                    const currentTime = now().valueOf()
                    const cutoff = currentTime - RECENT_FILTER_MAX_AGE_MS

                    const entry: RecentTaxonomicFilter = {
                        groupType,
                        groupName,
                        value,
                        item,
                        timestamp: currentTime,
                        ...(teamId ? { teamId } : {}),
                        ...(propertyFilter ? { propertyFilter } : {}),
                    }

                    const withoutDuplicate = state.filter((f) => {
                        if (f.groupType !== groupType || f.value !== value) {
                            return true
                        }
                        if (incomingComplete && !isCompleteRecentPropertyFilter(f.propertyFilter)) {
                            return false
                        }
                        return !isDuplicateRecentFilter(f, { groupType, value, propertyFilter })
                    })

                    const withoutExpired = withoutDuplicate.filter((f) => f.timestamp > cutoff)

                    return [entry, ...withoutExpired].slice(0, MAX_RECENT_FILTERS)
                },
            },
        ],
    }),
    selectors({
        recentFilterItems: [
            (s) => [s.recentFilters],
            (recentFilters: RecentTaxonomicFilter[]): TaxonomicDefinitionTypes[] =>
                recentFilters.map(
                    (f) =>
                        ({
                            ...f.item,
                            _recentContext: {
                                sourceGroupType: f.groupType,
                                sourceGroupName: f.groupName,
                                teamId: f.teamId,
                                propertyFilter: f.propertyFilter,
                            } as RecentItemContext,
                        }) as unknown as TaxonomicDefinitionTypes
                ),
        ],
    }),
    permanentlyMount(),
])
