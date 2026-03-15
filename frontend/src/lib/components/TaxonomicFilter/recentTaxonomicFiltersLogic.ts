import { actions, kea, path, reducers, selectors } from 'kea'

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
    value: TaxonomicFilterValue
    item: Record<string, any>
    timestamp: number
    teamId?: number
    propertyFilter?: AnyPropertyFilter
}

export const recentTaxonomicFiltersLogic = kea<recentTaxonomicFiltersLogicType>([
    path(['lib', 'components', 'TaxonomicFilter', 'recentTaxonomicFiltersLogic']),
    actions({
        recordRecentFilter: (
            groupType: TaxonomicFilterGroupType,
            value: TaxonomicFilterValue,
            item: any,
            teamId?: number,
            propertyFilter?: AnyPropertyFilter
        ) => ({
            groupType,
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
                recordRecentFilter: (state, { groupType, value, item, teamId, propertyFilter }) => {
                    if (EXCLUDED_GROUP_TYPES.has(groupType) || value == null) {
                        return state
                    }

                    const currentTime = now().valueOf()
                    const cutoff = currentTime - RECENT_FILTER_MAX_AGE_MS

                    const entry: RecentTaxonomicFilter = {
                        groupType,
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
    selectors({
        recentFilterItems: [
            (s) => [s.recentFilters],
            (recentFilters: RecentTaxonomicFilter[]): Record<string, any>[] =>
                recentFilters.map((f) => ({
                    ...f.item,
                    group: f.groupType,
                    _recentTeamId: f.teamId,
                    ...(f.propertyFilter ? { _recentPropertyFilter: f.propertyFilter } : {}),
                })),
        ],
    }),
    permanentlyMount(),
])
