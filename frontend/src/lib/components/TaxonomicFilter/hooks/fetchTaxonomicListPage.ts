/**
 * Pure-ish data fetcher used by useGroupList. Translates a (group, page, query)
 * tuple into a single API request and returns a normalised page result.
 *
 * Kept separate from the React hook so it can be tested in isolation and
 * later swapped out for a TanStack Query queryFn.
 */
import { combineUrl } from 'kea-router'

import api from 'lib/api'
import { ListStorage, TaxonomicFilterGroup } from 'lib/components/TaxonomicFilter/types'

export interface FetchTaxonomicPageParams {
    group: TaxonomicFilterGroup
    searchQuery: string
    offset: number
    limit: number
    isExpanded: boolean
    showNumericalPropsOnly?: boolean
    hideBehavioralCohorts?: boolean
    signal?: AbortSignal
}

const EMPTY_LIST: ListStorage = { results: [], searchQuery: '', count: 0 }

export async function fetchTaxonomicListPage({
    group,
    searchQuery,
    offset,
    limit,
    isExpanded,
    showNumericalPropsOnly,
    hideBehavioralCohorts,
}: FetchTaxonomicPageParams): Promise<ListStorage> {
    const remoteEndpoint = group.endpoint
    if (!remoteEndpoint) {
        return { ...EMPTY_LIST, searchQuery }
    }

    const minSearchQueryLength = group.minSearchQueryLength ?? 0
    if (minSearchQueryLength > 0 && searchQuery.length < minSearchQueryLength) {
        return { ...EMPTY_LIST, searchQuery }
    }

    const searchAlias = group.searchAlias || 'search'
    const excluded =
        group.excludedProperties && group.excludedProperties.length > 0
            ? JSON.stringify(group.excludedProperties)
            : undefined
    const properties = group.propertyAllowList ? group.propertyAllowList.join(',') : undefined

    const baseParams: Record<string, any> = {
        [searchAlias]: searchQuery,
        limit,
        offset,
        excluded_properties: excluded,
        properties,
    }
    if (showNumericalPropsOnly) {
        baseParams.is_numerical = 'true'
    }
    if (hideBehavioralCohorts) {
        baseParams.hide_behavioral_cohorts = 'true'
    }

    const useScoped = group.scopedEndpoint && !isExpanded
    const primaryUrl = useScoped ? group.scopedEndpoint! : remoteEndpoint

    const [primary, expandedCount] = await Promise.all([
        api.get(combineUrl(primaryUrl, baseParams).url, { signal }),
        useScoped
            ? api.get(combineUrl(remoteEndpoint, { ...baseParams, limit: 1, offset: 0 }).url, { signal })
            : Promise.resolve(null),
    ])

    const results = primary?.results ?? primary ?? []
    const count = primary?.count ?? (Array.isArray(primary) ? primary.length : results.length)

    return {
        results,
        searchQuery,
        count,
        expandedCount: expandedCount?.count,
    }
}
