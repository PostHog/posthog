import { actions, kea, path, reducers } from 'kea'

import { now } from 'lib/dayjs'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { AnyPropertyFilter } from '~/types'

import type { recentTaxonomicFiltersLogicType } from './recentTaxonomicFiltersLogicType'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from './types'

export const MAX_RECENT_FILTERS = 20
export const RECENT_FILTER_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000

const EXCLUDED_GROUP_TYPES = new Set<TaxonomicFilterGroupType>([
    TaxonomicFilterGroupType.HogQLExpression,
    TaxonomicFilterGroupType.SuggestedFilters,
    TaxonomicFilterGroupType.RecentFilters,
    TaxonomicFilterGroupType.Empty,
    TaxonomicFilterGroupType.Wildcards,
    TaxonomicFilterGroupType.MaxAIContext,
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
    }),
    reducers({
        recentFilters: [
            [] as RecentTaxonomicFilter[],
            { persist: true },
            {
                recordRecentFilter: (state, { groupType, groupName, value, item, teamId, propertyFilter }) => {
                    if (EXCLUDED_GROUP_TYPES.has(groupType) || value == null) {
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

                    const withoutDuplicate = state.filter((f) => !(f.groupType === groupType && f.value === value))

                    const withoutExpired = withoutDuplicate.filter((f) => f.timestamp > cutoff)

                    return [entry, ...withoutExpired].slice(0, MAX_RECENT_FILTERS)
                },
            },
        ],
    }),
    permanentlyMount(),
])
