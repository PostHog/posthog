import { actions, connect, events, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import {
    expandRecentsForDisplay,
    hasRecentContext,
    recentTaxonomicFiltersLogic,
} from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { MAX_TOP_MATCHES_PER_GROUP, taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    hasPinnedContext,
    taxonomicFilterPinnedPropertiesLogic,
} from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import { legacyTaxonomicSurface } from 'lib/components/TaxonomicFilter/taxonomicFilterSurface'
import {
    ExcludedOperators,
    ExcludedProperties,
    InfiniteListLogicProps,
    META_GROUP_TYPES,
    QuickFilterItem,
    SkeletonItem,
    isQuickFilterItem,
    isSkeletonItem,
    ListFuse,
    ListStorage,
    LoaderOptions,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import {
    buildUrlContainsShortcut,
    COLLAPSED_TO_CONTAINS_ROW,
    partitionContainsShortcuts,
} from 'lib/components/TaxonomicFilter/utils/collapsedContainsRow'
import {
    floatRecentAndPinnedToTop,
    groupItemKey,
    pinnedSourceKey,
    recentSourceKey,
} from 'lib/components/TaxonomicFilter/utils/floatRecentPinned'
import { floatToFront } from 'lib/components/TaxonomicFilter/utils/floatToFront'
import { promoteMatchingProperties } from 'lib/components/TaxonomicFilter/utils/promoteProperties'
import { FEATURE_FLAGS } from 'lib/constants'
import { createFuse } from 'lib/utils/fuseSearch'
import { mapGroupQueryResponse } from 'lib/utils/groups'

import { filterExactSearchOnlyItems, getCoreFilterDefinition } from '~/taxonomy/helpers'
import { CohortType, EventDefinition, GroupTypeIndex, PropertyType } from '~/types'

import { teamLogic } from '../../../scenes/teamLogic'
import { getItemGroup } from './InfiniteList'
import type { infiniteListLogicType } from './infiniteListLogicType'

function pinnedItemMatchesSearch(
    item: TaxonomicDefinitionTypes,
    query: string,
    taxonomicGroups: TaxonomicFilterGroup[]
): boolean {
    const sourceGroup = hasPinnedContext(item)
        ? taxonomicGroups.find((g) => g.type === item._pinnedContext.sourceGroupType)
        : undefined
    const name = sourceGroup?.getName?.(item) || ('name' in item ? item.name : '') || ''
    const label = sourceGroup ? getCoreFilterDefinition(name, sourceGroup.type)?.label : undefined
    return name.toLowerCase().includes(query) || (label?.toLowerCase().includes(query) ?? false)
}

function recentItemMatchesSearch(
    item: TaxonomicDefinitionTypes,
    query: string,
    taxonomicGroups: TaxonomicFilterGroup[]
): boolean {
    if (!hasRecentContext(item)) {
        return false
    }
    const sourceGroup = taxonomicGroups.find((g) => g.type === item._recentContext.sourceGroupType)
    const name = sourceGroup?.getName?.(item) || ('name' in item ? item.name : '') || ''
    if (name.toLowerCase().includes(query)) {
        return true
    }
    const label = sourceGroup ? getCoreFilterDefinition(name, sourceGroup.type)?.label : undefined
    if (label?.toLowerCase().includes(query)) {
        return true
    }
    const propertyFilter = item._recentContext.propertyFilter
    if (propertyFilter) {
        const recentLabel = formatPropertyLabel(propertyFilter, {})
        if (recentLabel?.toLowerCase().includes(query)) {
            return true
        }
    }
    return false
}

function withoutPinnedDuplicatesOfRecents(
    pinnedItems: TaxonomicDefinitionTypes[],
    recentItems: TaxonomicDefinitionTypes[]
): TaxonomicDefinitionTypes[] {
    const recentKeys = new Set(recentItems.map(recentSourceKey).filter((key): key is string => key != null))
    if (recentKeys.size === 0) {
        return pinnedItems
    }
    return pinnedItems.filter((item) => {
        const key = pinnedSourceKey(item)
        return key == null || !recentKeys.has(key)
    })
}

export interface RowInfo {
    startIndex: number
    stopIndex: number
    overscanStopIndex: number
}

/*
 by default the pop-up starts open for the first item in the list
 this can be used with actions.setIndex to allow a caller to override that
 */
export const NO_ITEM_SELECTED = -1

// Data-warehouse tabs keep their own committed-selection affordance (the pinned,
// auto-expanded row via `getInitialPinnedRowIndex`), so they are excluded from
// the generic selection-promotion below.
const DATA_WAREHOUSE_GROUP_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.DataWarehouse,
    TaxonomicFilterGroupType.DataWarehouseSourceTables,
]

export function getInitialPinnedRowIndex({
    results,
    taxonomicGroups,
    group,
    listGroupType,
    groupType,
    value,
    isActiveTab,
}: {
    results: (TaxonomicDefinitionTypes | SkeletonItem)[]
    taxonomicGroups: TaxonomicFilterGroup[]
    group: TaxonomicFilterGroup | undefined
    listGroupType: TaxonomicFilterGroupType
    groupType: TaxonomicFilterGroupType | undefined
    value: string | number | null | undefined
    isActiveTab: boolean
}): number | null {
    if (
        !isActiveTab ||
        !DATA_WAREHOUSE_GROUP_TYPES.includes(listGroupType) ||
        groupType === undefined ||
        !DATA_WAREHOUSE_GROUP_TYPES.includes(groupType) ||
        value == null
    ) {
        return null
    }

    const selectedIndex = results.findIndex((result) => {
        if (isSkeletonItem(result)) {
            return false
        }

        return getItemGroup(result, taxonomicGroups, group)?.getValue?.(result) === value
    })

    return selectedIndex >= 0 ? selectedIndex : null
}

function appendAtIndex<T>(array: T[], items: any[], startIndex?: number): T[] {
    if (startIndex === undefined) {
        return [...array, ...items]
    }
    const arrayCopy = [...array]
    items.forEach((item, i) => {
        arrayCopy[startIndex + i] = item
    })
    return arrayCopy
}

const createEmptyListStorage = (searchQuery = '', first = false): ListStorage => ({
    results: [],
    searchQuery,
    count: 0,
    first,
})

// simple cache with a setTimeout expiry
const API_CACHE_TIMEOUT = 60000
let apiCache: Record<string, ListStorage> = {}
let apiCacheTimers: Record<string, number> = {}

type ListResponse = unknown[] | { results?: unknown[]; count?: number }

function responseHasResults(response: ListResponse): boolean {
    if (Array.isArray(response)) {
        return response.length > 0
    }
    return (response?.results?.length ?? 0) > 0 || (response?.count ?? 0) > 0
}

/** Reset the module-level API cache. */
export function clearApiCache(): void {
    Object.values(apiCacheTimers).forEach((timerId) => window.clearTimeout(timerId))
    apiCache = {}
    apiCacheTimers = {}
}

async function fetchCachedListResponse(path: string, searchParams: Record<string, any>): Promise<ListStorage> {
    const url = combineUrl(path, searchParams).url
    if (apiCache[url]) {
        return apiCache[url]
    }
    const response = await api.get(url)
    // Never cache an empty response. A transient empty result (a backend blip, a race) would
    // otherwise be pinned for the full timeout, so an event that actually exists keeps reading as
    // "No results" for up to a minute — retrying the same query just re-reads the cached blank.
    // Only successful, non-empty responses are safe to reuse.
    if (responseHasResults(response)) {
        apiCache[url] = response
        apiCacheTimers[url] = window.setTimeout(() => {
            delete apiCache[url]
            delete apiCacheTimers[url]
        }, API_CACHE_TIMEOUT)
    }
    return response
}

export const infiniteListLogic = kea<infiniteListLogicType>([
    props({ showNumericalPropsOnly: false, minSearchQueryLength: undefined } as InfiniteListLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}-${props.listGroupType}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'infiniteListLogic', key]),

    connect((props: InfiniteListLogicProps) => ({
        values: [
            taxonomicFilterLogic(props),
            [
                'activeTab',
                'searchQuery',
                'value',
                'groupType',
                'taxonomicGroups',
                'taxonomicGroupTypes',
                'topMatchItemsWithSkeletons',
                'anyGroupLoading',
                'includeStaleEvents',
            ],
            teamLogic,
            ['currentTeamId'],
            recentTaxonomicFiltersLogic,
            ['recentFilterItems'],
            taxonomicFilterPinnedPropertiesLogic,
            ['pinnedFilterItems'],
        ],
        actions: [
            taxonomicFilterLogic(props),
            ['setSearchQuery', 'setActiveTab', 'selectItem', 'infiniteListResultsReceived', 'setIncludeStaleEvents'],
        ],
    })),
    actions({
        selectSelected: true,
        moveUp: true,
        moveDown: true,
        setIndex: (index: number) => ({ index }),
        setPinnedRowIndex: (pinnedRowIndex: number | null) => ({ pinnedRowIndex }),
        togglePinnedRow: (rowIndex: number) => ({ rowIndex }),
        resetPinnedRowState: true,
        applyInitialPinnedRow: (rowIndex: number) => ({ rowIndex }),
        reconcilePinnedRowState: true,
        setLimit: (limit: number) => ({ limit }),
        onRowsRendered: (rowInfo: RowInfo) => ({ rowInfo }),
        loadRemoteItems: (options: LoaderOptions) => options,
        updateRemoteItem: (item: TaxonomicDefinitionTypes) => ({ item }),
        expand: true,
        abortAnyRunningQuery: true,
        setHasMore: (hasMore: boolean) => ({ hasMore }),
        remoteItemsFetchFailedForQuery: (searchQuery: string) => ({ searchQuery }),
    }),
    loaders(({ actions, values, cache, props }) => ({
        remoteItems: [
            createEmptyListStorage('', true),
            {
                loadRemoteItems: async ({ offset, limit }, breakpoint) => {
                    if (!values.remoteItems.first) {
                        await breakpoint(500)
                    } else {
                        // These connected values below might be read before they are available due to circular logic mounting.
                        // Adding a slight delay (breakpoint) fixes this.
                        await breakpoint(1)
                    }

                    const {
                        isExpanded,
                        remoteEndpoint,
                        scopedRemoteEndpoint,
                        searchQuery,
                        excludedProperties,
                        listGroupType,
                        propertyAllowList,
                        minSearchQueryLength,
                    } = values

                    if (!remoteEndpoint) {
                        return createEmptyListStorage(searchQuery)
                    }

                    if (minSearchQueryLength > 0 && searchQuery.length < minSearchQueryLength) {
                        return createEmptyListStorage(searchQuery)
                    }

                    const eventsTab =
                        listGroupType === TaxonomicFilterGroupType.Events ||
                        listGroupType === TaxonomicFilterGroupType.CustomEvents
                    const searchParams = {
                        [`${values.group?.searchAlias || 'search'}`]: searchQuery,
                        limit,
                        offset,
                        excluded_properties:
                            excludedProperties && excludedProperties.length > 0
                                ? JSON.stringify(excludedProperties)
                                : undefined,
                        properties: propertyAllowList ? propertyAllowList.join(',') : undefined,
                        ...(props.showNumericalPropsOnly ? { is_numerical: 'true' } : {}),
                        // TODO: remove this filter once we can support behavioral cohorts for feature flags, it's only
                        // used in the feature flag property filter UI
                        ...(props.hideBehavioralCohorts ? { hide_behavioral_cohorts: 'true' } : {}),
                        ...(eventsTab && !values.includeStaleEvents ? { exclude_stale: 'true' } : {}),
                    }

                    const start = performance.now()
                    actions.abortAnyRunningQuery()

                    let response: any
                    let expandedCountResponse: any = null

                    try {
                        // Querying groups from /groups/ endpoint may result in query timeouts. Let's query clickhouse instead
                        const isGroupNamesFilter = values.listGroupType.startsWith(
                            TaxonomicFilterGroupType.GroupNamesPrefix
                        )
                        if (isGroupNamesFilter && values.group?.groupTypeIndex !== undefined) {
                            const groupsResponse = await api.groups.listClickhouse({
                                group_type_index: values.group.groupTypeIndex as GroupTypeIndex,
                                search: searchQuery || '',
                                limit,
                            })

                            const transformedGroups = mapGroupQueryResponse(groupsResponse)
                            response = {
                                results: transformedGroups,
                                count: transformedGroups.length,
                            }
                            actions.setHasMore(groupsResponse.hasMore || false)
                            if (scopedRemoteEndpoint && !isExpanded) {
                                expandedCountResponse = { count: transformedGroups.length }
                            }
                        } else {
                            // Use the original REST API for non-groups endpoints
                            const [apiResponse, expandedApiResponse] = await Promise.all([
                                // get the list of results
                                fetchCachedListResponse(
                                    scopedRemoteEndpoint && !isExpanded ? scopedRemoteEndpoint : remoteEndpoint,
                                    searchParams
                                ),
                                // if this is an unexpanded scoped list, get the count for the full list
                                scopedRemoteEndpoint && !isExpanded
                                    ? fetchCachedListResponse(remoteEndpoint, {
                                          ...searchParams,
                                          limit: 1,
                                          offset: 0,
                                      })
                                    : null,
                            ])
                            response = apiResponse
                            expandedCountResponse = expandedApiResponse
                        }
                    } catch (error: any) {
                        if (!isBreakpoint(error)) {
                            // Carry the query that was in flight when this run errored so the
                            // reducer can attribute the failure to the right query string.
                            actions.remoteItemsFetchFailedForQuery(searchQuery)
                        }
                        throw error
                    }
                    breakpoint()

                    const queryChanged = values.remoteItems.searchQuery !== searchQuery
                    const existingResults = values.remoteItems.results
                    cache.abortController = null

                    // Drop legacy/deprecated definitions that only surface on an exact query
                    // (mirrors the rebuild's fetchTaxonomicListPage). Narrow legacy searches
                    // return a single page, so filtering here doesn't disturb offset mapping.
                    const rawResults: any[] = response.results || response
                    const filteredResults = filterExactSearchOnlyItems(
                        rawResults,
                        (item) => values.group?.getName?.(item) ?? (item as { name?: string })?.name,
                        listGroupType,
                        searchQuery
                    )
                    const removedCount = rawResults.length - filteredResults.length
                    const rawCount =
                        response.count ||
                        (Array.isArray(response) ? response.length : 0) ||
                        (response.results || []).length

                    return {
                        results: appendAtIndex(queryChanged ? [] : existingResults, filteredResults, offset),
                        searchQuery,
                        queryChanged,
                        // Only the initial page times the search; "load more" (offset > 0)
                        // would otherwise overwrite it with pagination latency.
                        loadDurationMs: offset === 0 ? Math.floor(performance.now() - start) : undefined,
                        count: Math.max(0, rawCount - removedCount),
                        expandedCount: expandedCountResponse?.count,
                    }
                },
                updateRemoteItem: ({ item }) => {
                    // On updating item, invalidate cache
                    clearApiCache()
                    const popFromResults = 'hidden' in item && item.hidden
                    const results: TaxonomicDefinitionTypes[] = values.remoteItems.results
                        .map((i) => (i.name === item.name ? (popFromResults ? null : item) : i))
                        .filter((i): i is TaxonomicDefinitionTypes => i !== null)
                    return {
                        ...values.remoteItems,
                        results,
                    }
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        index: [
            (props.selectFirstItem === false || props.autoSelectItem === false ? NO_ITEM_SELECTED : 0) as number,
            {
                setIndex: (_, { index }) => index,
                loadRemoteItemsSuccess: (state, { remoteItems }) =>
                    remoteItems.queryChanged ? (props.autoSelectItem === false ? NO_ITEM_SELECTED : 0) : state,
            },
        ],
        pinnedRowIndex: [
            null as number | null,
            {
                setPinnedRowIndex: (_, { pinnedRowIndex }) => pinnedRowIndex,
                togglePinnedRow: (state, { rowIndex }) => (state === rowIndex ? null : rowIndex),
                applyInitialPinnedRow: (_, { rowIndex }) => rowIndex,
                resetPinnedRowState: () => null,
            },
        ],
        hasAppliedInitialPin: [
            false,
            {
                applyInitialPinnedRow: () => true,
                resetPinnedRowState: () => false,
            },
        ],
        showPopover: [props.popoverEnabled !== false, {}],
        limit: [
            100,
            {
                setLimit: (_, { limit }) => limit,
            },
        ],
        startIndex: [0, { onRowsRendered: (_, { rowInfo: { startIndex } }) => startIndex }],
        stopIndex: [0, { onRowsRendered: (_, { rowInfo: { stopIndex } }) => stopIndex }],
        isExpanded: [false, { expand: () => true }],
        hasMore: [false, { setHasMore: (_, { hasMore }) => hasMore }],
        // Tracks the searchQuery whose fetch failed. Using the query (not a boolean) prevents
        // a stale out-of-order failure from settling a newer in-flight request — only a failure
        // for the _current_ query should count as settled.
        remoteFetchFailed: [
            null as string | null,
            {
                loadRemoteItems: () => null,
                loadRemoteItemsSuccess: () => null,
                remoteItemsFetchFailedForQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
    })),
    selectors({
        listGroupType: [(_, p) => [p.listGroupType], (listGroupType) => listGroupType],
        isSuggestedFilters: [
            (s) => [s.listGroupType],
            (listGroupType: TaxonomicFilterGroupType): boolean =>
                listGroupType === TaxonomicFilterGroupType.SuggestedFilters,
        ],
        trimmedSearchQuery: [(s) => [s.searchQuery], (searchQuery) => searchQuery.trim()],
        isActiveTab: [
            (s) => [s.listGroupType, s.activeTab],
            (listGroupType, activeTab): boolean => listGroupType === activeTab,
        ],
        contextFilteredRecentItems: [
            (s) => [
                s.recentFilterItems,
                s.taxonomicGroupTypes,
                (_, props: InfiniteListLogicProps) => props.excludedOperators,
                (_, props: InfiniteListLogicProps) => props.selectingKeyOnly,
                (_, props: InfiniteListLogicProps) => props.excludedProperties,
            ],
            (
                recentFilterItems: TaxonomicDefinitionTypes[],
                taxonomicGroupTypes: TaxonomicFilterGroupType[],
                excludedOperators: ExcludedOperators | undefined,
                selectingKeyOnly: boolean | undefined,
                excludedProperties: ExcludedProperties | undefined
            ): TaxonomicDefinitionTypes[] => {
                if (!recentFilterItems?.length) {
                    return []
                }
                const availableTypes = new Set(taxonomicGroupTypes)
                const inScope = recentFilterItems.filter((item) => {
                    if (!hasRecentContext(item) || !availableTypes.has(item._recentContext.sourceGroupType)) {
                        return false
                    }
                    // A group's excluded values (e.g. `message` for the logs group-by picker) must be
                    // dropped from the Recent tab too, not just the group's own option list — otherwise
                    // an excluded key recorded elsewhere leaks back in as a selectable recent.
                    const excludedValues = excludedProperties?.[item._recentContext.sourceGroupType]
                    if (excludedValues?.length && excludedValues.includes(item._recentContext.sourceValue)) {
                        return false
                    }
                    const excludedForGroup = excludedOperators?.[item._recentContext.sourceGroupType]
                    if (excludedForGroup?.length) {
                        const propertyFilter = item._recentContext.propertyFilter
                        const operator =
                            propertyFilter && 'operator' in propertyFilter ? propertyFilter.operator : undefined
                        if (operator && excludedForGroup.includes(operator)) {
                            return false
                        }
                    }
                    return true
                })
                return expandRecentsForDisplay(inScope, selectingKeyOnly)
            },
        ],
        contextFilteredPinnedItems: [
            (s) => [s.pinnedFilterItems, s.taxonomicGroupTypes],
            (
                pinnedFilterItems: TaxonomicDefinitionTypes[],
                taxonomicGroupTypes: TaxonomicFilterGroupType[]
            ): TaxonomicDefinitionTypes[] => {
                if (!pinnedFilterItems?.length) {
                    return []
                }
                const availableTypes = new Set(taxonomicGroupTypes)
                return pinnedFilterItems.filter(
                    (item) => hasPinnedContext(item) && availableTypes.has(item._pinnedContext.sourceGroupType)
                )
            },
        ],
        // This list is the filter's only substantive (non-meta) group. There are no separate
        // Recent/Pinned tabs leading the filter, so this list floats recent/pinned items to
        // the top of its own results instead (see `items`).
        isSoleSubstantiveGroup: [
            (s) => [s.listGroupType, s.taxonomicGroupTypes],
            (listGroupType, taxonomicGroupTypes: TaxonomicFilterGroupType[]): boolean => {
                const substantive = taxonomicGroupTypes.filter((t) => !META_GROUP_TYPES.has(t))
                return substantive.length === 1 && substantive[0] === listGroupType
            },
        ],
        // Whether the sole substantive group has a usable getValue function for
        // floating recent/pinned items. The `items` selector reads this boolean
        // (stable reference) rather than a function (unstable closure that would
        // defeat kea's reference-equality memoisation and cause infinite re-renders).
        soleGroupHasGetValue: [
            (s) => [s.isSoleSubstantiveGroup, s.listGroupType, s.taxonomicGroups],
            (
                isSoleSubstantiveGroup: boolean,
                listGroupType: TaxonomicFilterGroupType,
                taxonomicGroups: TaxonomicFilterGroup[]
            ): boolean => {
                if (!isSoleSubstantiveGroup) {
                    return false
                }
                return !!taxonomicGroups.find((g) => g.type === listGroupType)?.getValue
            },
        ],
        allowNonCapturedEvents: [
            () => [(_, props) => props.allowNonCapturedEvents],
            (allowNonCapturedEvents: boolean | undefined) => allowNonCapturedEvents ?? false,
        ],
        isLocalDataLoading: [
            (selectors) => [
                (state, props: InfiniteListLogicProps) => {
                    if (props.listGroupType === TaxonomicFilterGroupType.DataWarehouseProperties) {
                        return props.schemaColumnsLoading ?? false
                    }

                    const taxonomicGroups = selectors.taxonomicGroups(state)
                    const group = taxonomicGroups.find((g) => g.type === props.listGroupType)

                    if (group?.logic && group?.valueLoading) {
                        return group.logic.selectors[group.valueLoading]?.(state) ?? false
                    }
                    return false
                },
            ],
            (isLocalDataLoading: boolean) => isLocalDataLoading,
        ],
        isLoading: [(s) => [s.remoteItemsLoading], (remoteItemsLoading) => remoteItemsLoading],
        group: [
            (s) => [s.listGroupType, s.taxonomicGroups],
            (listGroupType, taxonomicGroups): TaxonomicFilterGroup | undefined =>
                taxonomicGroups.find((g) => g.type === listGroupType),
        ],
        remoteEndpoint: [(s) => [s.group], (group) => group?.endpoint || null],
        minSearchQueryLength: [
            (s) => [s.group, (_, props) => props.minSearchQueryLength],
            (group, propsMinSearchQueryLength) => propsMinSearchQueryLength ?? group?.minSearchQueryLength ?? 0,
        ],
        needsMoreSearchCharacters: [
            (s) => [s.minSearchQueryLength, s.searchQuery],
            (minSearchQueryLength, searchQuery) => {
                if (minSearchQueryLength <= 0) {
                    return false
                }

                return searchQuery.trim().length < minSearchQueryLength
            },
        ],
        excludedProperties: [(s) => [s.group], (group) => group?.excludedProperties],
        propertyAllowList: [(s) => [s.group], (group) => group?.propertyAllowList],
        scopedRemoteEndpoint: [(s) => [s.group], (group) => group?.scopedEndpoint || null],
        hasRenderFunction: [(s) => [s.group], (group) => !!group?.render],
        isExpandable: [
            (s) => [s.remoteEndpoint, s.scopedRemoteEndpoint, s.remoteItems],
            (remoteEndpoint, scopedRemoteEndpoint, remoteItems) =>
                !!(
                    remoteEndpoint &&
                    scopedRemoteEndpoint &&
                    remoteItems.expandedCount &&
                    remoteItems.expandedCount > remoteItems.count
                ),
        ],
        isExpandableButtonSelected: [
            (s) => [s.isExpandable, s.index, s.totalListCount],
            (isExpandable, index, totalListCount) => isExpandable && index === totalListCount - 1,
        ],
        hasRemoteDataSource: [(s) => [s.remoteEndpoint], (remoteEndpoint) => !!remoteEndpoint],
        remoteResultsAreFresh: [
            (s) => [s.hasRemoteDataSource, s.remoteItems, s.searchQuery, s.remoteFetchFailed],
            (
                hasRemoteDataSource: boolean,
                remoteItems: ListStorage,
                searchQuery: string,
                remoteFetchFailed: string | null
            ): boolean => {
                // Local-only groups resolve synchronously — always fresh.
                const isLocalOnly = !hasRemoteDataSource
                // A failed fetch for *this* query counts as settled. We check the exact query
                // rather than a bare boolean so that an out-of-order stale failure (run A failing
                // after run B is already in flight) doesn't incorrectly settle run B's result.
                const currentQueryFailed = remoteFetchFailed === searchQuery
                const currentQuerySettled = (remoteItems.searchQuery ?? '') === searchQuery
                return isLocalOnly || currentQueryFailed || currentQuerySettled
            },
        ],
        showNonCapturedEventOption: [
            (s) => [s.allowNonCapturedEvents, s.listGroupType, s.searchQuery, s.isLoading, s.results],
            (
                allowNonCapturedEvents: boolean,
                listGroupType: TaxonomicFilterGroupType,
                searchQuery: string,
                isLoading: boolean,
                results: TaxonomicDefinitionTypes[]
            ): boolean => {
                if (!allowNonCapturedEvents) {
                    return false
                }
                if (
                    listGroupType !== TaxonomicFilterGroupType.CustomEvents &&
                    listGroupType !== TaxonomicFilterGroupType.Events
                ) {
                    return false
                }
                if (searchQuery.trim().length === 0 || isLoading) {
                    return false
                }
                // Keyword-shortcut QuickFilterItems don't represent captured events — ignore them
                // when deciding whether to show the "not seen yet" escape hatch.
                const realResults = results.filter((item) => !isQuickFilterItem(item))
                return realResults.length === 0
            },
        ],
        showEmptyState: [
            (s) => [
                s.totalListCount,
                s.isLoading,
                s.isSuggestedFilters,
                s.anyGroupLoading,
                s.searchQuery,
                s.hasRemoteDataSource,
                s.showNonCapturedEventOption,
                s.needsMoreSearchCharacters,
                s.remoteResultsAreFresh,
            ],
            (
                totalListCount: number,
                isLoading: boolean,
                isSuggestedFilters: boolean,
                anyGroupLoading: boolean,
                searchQuery: string,
                hasRemoteDataSource: boolean,
                showNonCapturedEventOption: boolean,
                needsMoreSearchCharacters: boolean,
                remoteResultsAreFresh: boolean
            ): boolean =>
                (totalListCount === 0 &&
                    !isLoading &&
                    // Don't declare "No results" until the fetch for the *current* query has landed —
                    // otherwise a stale/empty list from the previous query masquerades as no matches.
                    remoteResultsAreFresh &&
                    !(isSuggestedFilters && anyGroupLoading && searchQuery.trim().length > 0) &&
                    (!!searchQuery || !hasRemoteDataSource) &&
                    !showNonCapturedEventOption) ||
                needsMoreSearchCharacters,
        ],
        showLoadingState: [
            (s) => [
                s.isLoading,
                s.isSuggestedFilters,
                s.anyGroupLoading,
                s.results,
                s.searchQuery,
                s.hasRemoteDataSource,
                s.remoteResultsAreFresh,
            ],
            (
                isLoading: boolean,
                isSuggestedFilters: boolean,
                anyGroupLoading: boolean,
                results: TaxonomicDefinitionTypes[],
                searchQuery: string,
                hasRemoteDataSource: boolean,
                remoteResultsAreFresh: boolean
            ): boolean =>
                (isLoading ||
                    (isSuggestedFilters && anyGroupLoading && searchQuery.trim().length > 0) ||
                    // The current-query remote fetch hasn't landed yet: keep the spinner up rather
                    // than flash a premature "No results". Gated on there being nothing to show
                    // (below) so still-valid rows aren't replaced by a spinner on every keystroke.
                    (hasRemoteDataSource && !remoteResultsAreFresh && searchQuery.trim().length > 0)) &&
                (!results || results.length === 0),
        ],
        rawLocalItems: [
            (selectors) => [
                (state, props: InfiniteListLogicProps) => {
                    if (props.listGroupType === TaxonomicFilterGroupType.RecentFilters) {
                        return selectors.contextFilteredRecentItems(state, props)
                    }
                    if (props.listGroupType === TaxonomicFilterGroupType.PinnedFilters) {
                        return selectors.contextFilteredPinnedItems(state, props)
                    }

                    const taxonomicGroups = selectors.taxonomicGroups(state)
                    const group = taxonomicGroups.find((g) => g.type === props.listGroupType)

                    if (group?.logic && group?.value) {
                        let items = group.logic.selectors[group.value]?.(state)

                        // Handle paginated responses for cohorts, which return a CountedPaginatedResponse
                        if (items?.results) {
                            items = items.results
                        }

                        return items
                    }
                    if (group?.options) {
                        return group.options
                    }
                    if (props.optionsFromProp && Object.keys(props.optionsFromProp).includes(props.listGroupType)) {
                        return props.optionsFromProp[props.listGroupType]
                    }
                    return null
                },
                (_, props: InfiniteListLogicProps) => props.listGroupType,
                (_, props: InfiniteListLogicProps) => props.showNumericalPropsOnly,
            ],
            (
                rawLocalItems: (EventDefinition | CohortType)[],
                listGroupType: TaxonomicFilterGroupType,
                showNumericalPropsOnly: boolean
            ) => {
                if (
                    showNumericalPropsOnly &&
                    listGroupType === TaxonomicFilterGroupType.DataWarehousePersonProperties
                ) {
                    return (rawLocalItems || []).filter(
                        (item) => 'property_type' in item && item.property_type === PropertyType.Numeric
                    )
                }

                return rawLocalItems
            },
        ],
        fuse: [
            (s) => [s.rawLocalItems, s.taxonomicGroups, s.group],
            (rawLocalItems, taxonomicGroups, group): ListFuse => {
                // maps e.g. "selector" to its display value "CSS Selector"
                // so a search of "css" matches something
                function asPostHogName(
                    g: TaxonomicFilterGroup | undefined,
                    item: EventDefinition | CohortType
                ): string | undefined {
                    return g ? getCoreFilterDefinition(g.getName?.(item), g.type)?.label : undefined
                }

                const haystack = (rawLocalItems || []).map((item) => {
                    const itemGroup = getItemGroup(item, taxonomicGroups, group)
                    const recentLabel =
                        hasRecentContext(item) && item._recentContext.propertyFilter
                            ? formatPropertyLabel(item._recentContext.propertyFilter, {})
                            : undefined
                    return {
                        name: itemGroup?.getName?.(item) || '',
                        posthogName: asPostHogName(itemGroup, item),
                        recentLabel,
                        item: item,
                    }
                })

                return createFuse(haystack, {
                    keys: ['name', 'posthogName', 'recentLabel'],
                    ignoreLocation: true,
                })
            },
        ],
        localItems: [
            (s) => [s.rawLocalItems, s.searchQuery, s.fuse, s.group],
            (rawLocalItems, searchQuery, fuse, group): ListStorage => {
                if (!group) {
                    return createEmptyListStorage()
                }
                if (group.localItemsSearch) {
                    const filtered = group.localItemsSearch(rawLocalItems || [], searchQuery)
                    return {
                        results: filtered,
                        count: filtered.length,
                        searchQuery,
                    }
                }

                if (rawLocalItems) {
                    const filteredItems = searchQuery
                        ? fuse.search(searchQuery).map((result) => result.item.item)
                        : rawLocalItems

                    return {
                        results: filteredItems,
                        count: filteredItems.length,
                        searchQuery,
                    }
                }
                return createEmptyListStorage()
            },
        ],
        topMatchesForQuery: [
            (s) => [
                s.localItems,
                s.remoteItems,
                s.searchQuery,
                s.hasRemoteDataSource,
                s.keywordShortcutItems,
                s.listGroupType,
                (_, props: InfiniteListLogicProps) => props.collapseUrlsToContainsRow,
            ],
            (
                localItems,
                remoteItems,
                searchQuery,
                hasRemoteDataSource,
                keywordShortcutItems,
                listGroupType,
                collapseUrlsToContainsRow
            ): TaxonomicDefinitionTypes[] => {
                if (!searchQuery) {
                    return []
                }
                const remoteIsFresh = remoteItems.searchQuery === searchQuery
                // Collapsed groups contribute the single "URL contains <query>" shortcut to the
                // aggregated SuggestedFilters / "All" tab too — not the raw URL matches — so the
                // common entry path collapses identically to the dedicated group list above.
                if (collapseUrlsToContainsRow && COLLAPSED_TO_CONTAINS_ROW.has(listGroupType)) {
                    const trimmed = searchQuery.trim()
                    const hasMatch = trimmed.length > 0 && remoteIsFresh && remoteItems.results.length > 0
                    return hasMatch ? [buildUrlContainsShortcut(trimmed, listGroupType)] : []
                }
                const results = hasRemoteDataSource ? (remoteIsFresh ? remoteItems.results : []) : localItems.results
                const realMatches = promoteMatchingProperties(results, searchQuery).slice(0, MAX_TOP_MATCHES_PER_GROUP)
                // Shortcuts lead the group's top-match contribution so the aggregated SuggestedFilters
                // tab surfaces them above real events with the same name.
                return [...keywordShortcutItems, ...realMatches]
            },
        ],
        suggestedPinnedMatches: [
            (s) => [s.contextFilteredPinnedItems, s.searchQuery, s.listGroupType, s.taxonomicGroups],
            (
                contextFilteredPinnedItems: TaxonomicDefinitionTypes[],
                searchQuery: string,
                listGroupType: TaxonomicFilterGroupType,
                taxonomicGroups: TaxonomicFilterGroup[]
            ): TaxonomicDefinitionTypes[] => {
                if (listGroupType !== TaxonomicFilterGroupType.SuggestedFilters || !searchQuery) {
                    return []
                }
                const q = searchQuery.trim().toLowerCase()
                return (contextFilteredPinnedItems || []).filter((item) =>
                    pinnedItemMatchesSearch(item, q, taxonomicGroups)
                )
            },
        ],
        suggestedRecentMatches: [
            (s) => [s.contextFilteredRecentItems, s.searchQuery, s.listGroupType, s.taxonomicGroups],
            (
                contextFilteredRecentItems: TaxonomicDefinitionTypes[],
                searchQuery: string,
                listGroupType: TaxonomicFilterGroupType,
                taxonomicGroups: TaxonomicFilterGroup[]
            ): TaxonomicDefinitionTypes[] => {
                if (listGroupType !== TaxonomicFilterGroupType.SuggestedFilters || !searchQuery) {
                    return []
                }
                const q = searchQuery.trim().toLowerCase()
                return (contextFilteredRecentItems || []).filter((item) =>
                    recentItemMatchesSearch(item, q, taxonomicGroups)
                )
            },
        ],
        keywordShortcutItems: [
            (s) => [s.group, s.searchQuery, (_, props) => props.enableKeywordShortcuts],
            (
                group: TaxonomicFilterGroup | undefined,
                searchQuery: string,
                enableKeywordShortcuts: boolean | undefined
            ): QuickFilterItem[] =>
                enableKeywordShortcuts && searchQuery.trim() ? (group?.keywordShortcuts?.(searchQuery) ?? []) : [],
        ],
        // Deduped per-group top matches for the SuggestedFilters tab: when a search surfaces the
        // same `{ groupType, value }` from a per-group top-match AND from a recent/pinned row,
        // drop the per-group row so the user doesn't see e.g. "Recent · pageview" stacked above
        // "Events · pageview". Extracted from `items` to keep that selector's input count down —
        // every extra input on `items` cascades into longer kea typegen times for downstream
        // logics.
        dedupedTopMatches: [
            (s) => [
                s.topMatchItemsWithSkeletons,
                s.listGroupType,
                s.searchQuery,
                s.contextFilteredRecentItems,
                s.contextFilteredPinnedItems,
                s.suggestedRecentMatches,
                s.suggestedPinnedMatches,
                s.taxonomicGroups,
            ],
            (
                topMatchItemsWithSkeletons,
                listGroupType,
                searchQuery,
                contextFilteredRecentItems,
                contextFilteredPinnedItems,
                suggestedRecentMatches,
                suggestedPinnedMatches,
                taxonomicGroups
            ): (TaxonomicDefinitionTypes | SkeletonItem)[] => {
                const isSuggested = listGroupType === TaxonomicFilterGroupType.SuggestedFilters
                if (!isSuggested) {
                    return []
                }
                const recentPrefix = !searchQuery ? (contextFilteredRecentItems || []).slice(0, 3) : []
                const pinnedPrefix = !searchQuery
                    ? withoutPinnedDuplicatesOfRecents(contextFilteredPinnedItems || [], recentPrefix).slice(0, 3)
                    : []

                const dedupeKeys = new Set<string>()
                const addRecentKey = (item: TaxonomicDefinitionTypes): void => {
                    const key = recentSourceKey(item)
                    if (key != null) {
                        dedupeKeys.add(key)
                    }
                }
                const addPinnedKey = (item: TaxonomicDefinitionTypes): void => {
                    const key = pinnedSourceKey(item)
                    if (key != null) {
                        dedupeKeys.add(key)
                    }
                }
                recentPrefix.forEach(addRecentKey)
                pinnedPrefix.forEach(addPinnedKey)
                suggestedRecentMatches.forEach(addRecentKey)
                suggestedPinnedMatches.forEach(addPinnedKey)

                if (dedupeKeys.size === 0) {
                    return topMatchItemsWithSkeletons
                }
                const groupsByType = new Map(taxonomicGroups.map((g) => [g.type, g]))
                return topMatchItemsWithSkeletons.filter((item) => {
                    if (isSkeletonItem(item)) {
                        return true
                    }
                    const group = (item as TaxonomicDefinitionTypes & { group?: TaxonomicFilterGroupType }).group
                    if (!group) {
                        return true
                    }
                    const value = groupsByType.get(group)?.getValue?.(item as TaxonomicDefinitionTypes)
                    if (value == null) {
                        return true
                    }
                    return !dedupeKeys.has(`${group}::${value}`)
                })
            },
        ],
        // The list's own group plus the committed selection, bundled into one input so
        // `items` stays within kea's 16-entry `SelectorTuple` cap (every extra input on
        // `items` also lengthens typegen for downstream logics, per the note on
        // `dedupedTopMatches`).
        selectionPromotionContext: [
            (s) => [s.group, s.groupType, s.value],
            (
                group,
                groupType,
                value
            ): {
                group: TaxonomicFilterGroup | undefined
                groupType: TaxonomicFilterGroupType | undefined
                value: TaxonomicFilterValue | undefined
            } => ({ group, groupType, value }),
        ],
        items: [
            (s) => [
                s.remoteItems,
                s.localItems,
                s.listGroupType,
                s.dedupedTopMatches,
                s.searchQuery,
                s.contextFilteredRecentItems,
                s.contextFilteredPinnedItems,
                s.suggestedPinnedMatches,
                s.suggestedRecentMatches,
                s.keywordShortcutItems,
                s.isSoleSubstantiveGroup,
                s.soleGroupHasGetValue,
                s.taxonomicGroups,
                s.selectionPromotionContext,
                (_, props: InfiniteListLogicProps) => props.collapseUrlsToContainsRow,
            ],
            (
                remoteItems,
                localItems,
                listGroupType,
                dedupedTopMatches,
                searchQuery,
                contextFilteredRecentItems,
                contextFilteredPinnedItems,
                suggestedPinnedMatches,
                suggestedRecentMatches,
                keywordShortcutItems,
                isSoleSubstantiveGroup,
                soleGroupHasGetValue,
                taxonomicGroups,
                selectionPromotionContext,
                collapseUrlsToContainsRow
            ) => {
                const { group, groupType, value } = selectionPromotionContext
                // Collapse URL groups to a single "URL contains <query>" shortcut row
                // (mirrors the rebuild menu's `COLLAPSED_TO_CONTAINS_ROW`). Only once
                // the remote fetch for the *current* query has returned at least one
                // match — otherwise the list is empty and the standard empty/loading
                // states apply.
                if (collapseUrlsToContainsRow && COLLAPSED_TO_CONTAINS_ROW.has(listGroupType)) {
                    const trimmed = (searchQuery ?? '').trim()
                    // The remote fetch is debounced and lags the typed query, so guard against a
                    // stale match from the previous query producing a shortcut for the new one.
                    const remoteIsFresh = (remoteItems.searchQuery ?? '').trim() === trimmed
                    const hasMatch = trimmed.length > 0 && remoteIsFresh && remoteItems.results.length > 0
                    const results = hasMatch ? [buildUrlContainsShortcut(trimmed, listGroupType)] : []
                    return {
                        results,
                        syntheticSelectedCount: 0,
                        count: results.length,
                        searchQuery: remoteItems.searchQuery,
                        queryChanged: remoteItems.queryChanged,
                        first: remoteItems.first,
                    }
                }
                const isSuggested = listGroupType === TaxonomicFilterGroupType.SuggestedFilters
                const recentPrefix = isSuggested && !searchQuery ? (contextFilteredRecentItems || []).slice(0, 3) : []
                // An item that is both recent and pinned shows once, under the section that
                // renders first — recents (mirrors the rebuild Combobox's prefix dedupe).
                const pinnedPrefix =
                    isSuggested && !searchQuery
                        ? withoutPinnedDuplicatesOfRecents(contextFilteredPinnedItems || [], recentPrefix).slice(0, 3)
                        : []
                const pinnedMatches = withoutPinnedDuplicatesOfRecents(suggestedPinnedMatches, suggestedRecentMatches)
                const topMatches = isSuggested ? dedupedTopMatches : []

                // Shortcuts lead the list so users searching for the verb they mean (e.g. "click")
                // see the autocapture/event-type shortcut prominently and pressing Enter picks it.
                // Real events with the same name remain accessible below the shortcut.
                // Recent matches appear next: they're computed locally and revealed immediately
                // so the user sees something useful while remote groups are still loading behind
                // the reveal barrier.
                const combinedResults = [
                    ...keywordShortcutItems,
                    ...recentPrefix,
                    ...pinnedPrefix,
                    ...suggestedRecentMatches,
                    ...pinnedMatches,
                    ...localItems.results,
                    ...remoteItems.results,
                    ...topMatches,
                ]
                // Reordering a windowed list would break onRowsRendered's display-index ->
                // remote-offset mapping (and sparse holes would crash the keyer), so only float
                // the sole group's recents/pinned once its list is fully loaded and dense.
                // Local-only groups (count 0, no remote) are always fully loaded.
                const soleGroupFullyLoaded =
                    remoteItems.results.length >= remoteItems.count && !combinedResults.includes(undefined as any)
                // Build the keyer inline (instead of a separate selector returning a
                // function) so kea's reference-equality memoisation isn't defeated by a
                // fresh closure on every evaluation.
                const shouldFloat =
                    !searchQuery && isSoleSubstantiveGroup && soleGroupHasGetValue && soleGroupFullyLoaded
                let orderedBase: typeof combinedResults
                if (searchQuery) {
                    orderedBase = promoteMatchingProperties(combinedResults, searchQuery)
                } else if (shouldFloat) {
                    const getValue = taxonomicGroups.find(
                        (g: TaxonomicFilterGroup) => g.type === listGroupType
                    )?.getValue
                    if (getValue) {
                        const keyOf = (item: TaxonomicDefinitionTypes): string | null =>
                            groupItemKey(listGroupType, getValue(item))
                        orderedBase = floatRecentAndPinnedToTop(
                            combinedResults,
                            keyOf,
                            contextFilteredRecentItems || [],
                            contextFilteredPinnedItems || []
                        )
                    } else {
                        orderedBase = combinedResults
                    }
                } else {
                    orderedBase = combinedResults
                }
                // Mirrors the rebuild menu's Combobox idle promotion: with no search query,
                // the committed selection leads the list so the user can see at a glance
                // what is currently picked — floated in place when the real row is loaded,
                // otherwise statically inserted as a synthetic row (the selection is known
                // at open; there's no need to wait for the loader). A leading null-valued
                // catch-all row (e.g. "All events") keeps its place, per the invariant in
                // floatRecentPinned.ts — so the selection targets index 1 when one is
                // present. While searching, relevance wins.
                let syntheticSelectedCount = 0
                if (
                    !searchQuery &&
                    value != null &&
                    // An empty string is not a real committed selection: it round-trips through
                    // `getValue` for name/value-keyed groups and would otherwise float a blank,
                    // clickable synthetic row that re-commits `''` on click. `0`/`false` are kept.
                    value !== '' &&
                    groupType &&
                    !META_GROUP_TYPES.has(groupType) &&
                    !DATA_WAREHOUSE_GROUP_TYPES.includes(groupType)
                ) {
                    const selectionKey = groupItemKey(groupType, value)
                    // A leading catch-all row (e.g. "All events") is a real, non-recent/pinned
                    // group option whose `getValue` resolves to `null` — not merely a recent/
                    // pinned row whose stripped shape happens to leave `getValue` undefined.
                    const leadingItem = orderedBase[0]
                    const leadingCatchAllOffset =
                        leadingItem != null &&
                        !isSkeletonItem(leadingItem) &&
                        !hasRecentContext(leadingItem) &&
                        !hasPinnedContext(leadingItem) &&
                        getItemGroup(leadingItem, taxonomicGroups, group)?.getValue?.(leadingItem) === null
                            ? 1
                            : 0
                    // The synthetic stand-in for a selection whose real row isn't loaded —
                    // shaped like a top match, so `getItemGroup` resolves its source group.
                    // Only usable when the source group round-trips it back to the committed
                    // value: id-keyed groups (actions, cohorts) read `.id`, which the
                    // `{ name, value, group }` shape lacks, so `getValue` returns `undefined`
                    // and the round-trip fails — keeping their raw ids out of the list, which
                    // is the intent. `name` stays the raw key, matching how real rows in
                    // name/value-keyed groups are shaped: it round-trips through `getValue`,
                    // and consumers that persist `item.name` verbatim don't get a friendly
                    // label baked in. Renderers already prettify raw keys at render time.
                    const sourceGroup = taxonomicGroups.find((g: TaxonomicFilterGroup) => g.type === groupType)
                    const synthetic = {
                        name: String(value),
                        value,
                        group: groupType,
                    } as unknown as TaxonomicDefinitionTypes
                    const syntheticRoundTrips = sourceGroup?.getValue?.(synthetic) === value
                    const insertSynthetic = (list: typeof orderedBase): typeof orderedBase =>
                        leadingCatchAllOffset > 0 ? [list[0], synthetic, ...list.slice(1)] : [synthetic, ...list]
                    if (isSuggested) {
                        // The aggregated list is fully client-side (recents/pinned prefixes),
                        // so both floating and prepending are safe here.
                        const selectedIndex = orderedBase.findIndex((item) => {
                            if (item == null || isSkeletonItem(item)) {
                                return false
                            }
                            if (recentSourceKey(item) === selectionKey || pinnedSourceKey(item) === selectionKey) {
                                return true
                            }
                            const itemGroup = getItemGroup(item, taxonomicGroups, group)
                            return (
                                groupItemKey(itemGroup?.type ?? listGroupType, itemGroup?.getValue?.(item) ?? null) ===
                                selectionKey
                            )
                        })
                        if (selectedIndex >= 0) {
                            orderedBase = floatToFront(orderedBase, selectedIndex, leadingCatchAllOffset)
                        } else if (syntheticRoundTrips) {
                            orderedBase = insertSynthetic(orderedBase)
                            syntheticSelectedCount = 1
                        }
                    } else if (groupType === listGroupType && group?.getValue) {
                        const getValue = group.getValue
                        const selectedIndex = orderedBase.findIndex(
                            (item) => item != null && !isSkeletonItem(item) && getValue(item) === value
                        )
                        if (selectedIndex === -1) {
                            // The selection isn't among the loaded rows (first page still in
                            // flight, or paginated past it) — insert the synthetic stand-in
                            // rather than waiting for the loader. Once the page carrying the
                            // real row lands, the `findIndex` above starts matching, the
                            // synthetic drops out, and the float below takes over: the loaded
                            // copy is the dedupe. The loader's display-index -> remote-offset
                            // mapping stays exact because `onRowsRendered` subtracts
                            // `syntheticSelectedCount` alongside `localItems.count`.
                            if (syntheticRoundTrips) {
                                orderedBase = insertSynthetic(orderedBase)
                                syntheticSelectedCount = 1
                            }
                        } else {
                            // Floating shifts every row above the selection down by one, so it
                            // is only safe when those rows are all loaded — a hole changing
                            // display position would desync the windowed loader's
                            // display-index -> remote-offset mapping.
                            const rowsAboveSelectionLoaded = (): boolean => {
                                for (let i = 0; i < selectedIndex; i++) {
                                    if (orderedBase[i] == null || isSkeletonItem(orderedBase[i])) {
                                        return false
                                    }
                                }
                                return true
                            }
                            if (selectedIndex > leadingCatchAllOffset && rowsAboveSelectionLoaded()) {
                                orderedBase = floatToFront(orderedBase, selectedIndex, leadingCatchAllOffset)
                            }
                        }
                    }
                }
                // The "URL contains <query>" shortcut leads the aggregated SuggestedFilters list —
                // ahead of recents/pinned/top-matches — so a URL search surfaces the contains
                // suggestion first. Everything else keeps its existing order.
                const [shortcutItems, otherItems] = partitionContainsShortcuts(orderedBase, (item) => item)
                const orderedResults = shortcutItems.length ? [...shortcutItems, ...otherItems] : orderedBase
                return {
                    results: orderedResults,
                    syntheticSelectedCount,
                    count:
                        syntheticSelectedCount +
                        keywordShortcutItems.length +
                        recentPrefix.length +
                        pinnedPrefix.length +
                        suggestedRecentMatches.length +
                        pinnedMatches.length +
                        localItems.count +
                        remoteItems.count +
                        topMatches.filter((item) => !isSkeletonItem(item)).length,
                    searchQuery: remoteItems.searchQuery || localItems.searchQuery,
                    expandedCount: remoteItems.expandedCount,
                    queryChanged: remoteItems.queryChanged,
                    first: localItems.first && remoteItems.first,
                }
            },
        ],
        totalResultCount: [(s) => [s.items], (items) => items.count || 0],
        totalExtraCount: [
            (s) => [s.isExpandable, s.hasRenderFunction],
            (isExpandable, hasRenderFunction) => (isExpandable ? 1 : 0) + (hasRenderFunction ? 1 : 0),
        ],
        totalListCount: [
            (s) => [s.totalResultCount, s.totalExtraCount],
            (totalResultCount, totalExtraCount) => totalResultCount + totalExtraCount,
        ],
        expandedCount: [(s) => [s.items], (items) => items.expandedCount || 0],
        results: [(s) => [s.items], (items) => items.results],
        showSuggestedFiltersEmptyState: [
            (s) => [s.isSuggestedFilters, s.trimmedSearchQuery, s.results],
            (isSuggestedFilters, trimmedSearchQuery, results): boolean =>
                isSuggestedFilters && !trimmedSearchQuery && results.length > 0,
        ],
        rowCount: [
            (s) => [
                s.showNonCapturedEventOption,
                s.results,
                s.isLoading,
                s.totalListCount,
                s.showSuggestedFiltersEmptyState,
            ],
            (showNonCapturedEventOption, results, isLoading, totalListCount, showSuggestedFiltersEmptyState): number =>
                showNonCapturedEventOption
                    ? 1
                    : Math.max(results.length || (isLoading ? 7 : 0), totalListCount || 0) +
                      (showSuggestedFiltersEmptyState ? 1 : 0),
        ],
        initialPinnedRowIndex: [
            (s) => [s.results, s.taxonomicGroups, s.group, s.listGroupType, s.groupType, s.value, s.isActiveTab],
            (results, taxonomicGroups, group, listGroupType, groupType, value, isActiveTab): number | null =>
                getInitialPinnedRowIndex({
                    results,
                    taxonomicGroups,
                    group,
                    listGroupType,
                    groupType,
                    value,
                    isActiveTab,
                }),
        ],
        selectedItem: [
            (s) => [s.index, s.items],
            (index, items): TaxonomicDefinitionTypes | undefined => {
                if (index < 0) {
                    return undefined
                }
                const item = items.results[index]
                if (!item || isSkeletonItem(item)) {
                    return undefined
                }
                return item
            },
        ],
        selectedItemValue: [
            (s) => [s.selectedItem, s.group],
            (selectedItem, group) => (selectedItem ? group?.getValue?.(selectedItem) || null : null),
        ],
        selectedItemInView: [
            (s) => [s.index, s.startIndex, s.stopIndex],
            (index, startIndex, stopIndex) => typeof index === 'number' && index >= startIndex && index <= stopIndex,
        ],
    }),
    listeners(({ values, actions, props, cache }) => ({
        reconcilePinnedRowState: () => {
            let nextPinnedRowIndex = values.pinnedRowIndex

            if (nextPinnedRowIndex !== null && nextPinnedRowIndex > values.rowCount - 1) {
                actions.setPinnedRowIndex(null)
                nextPinnedRowIndex = null
            }

            if (!values.hasAppliedInitialPin && nextPinnedRowIndex === null && values.initialPinnedRowIndex !== null) {
                actions.applyInitialPinnedRow(values.initialPinnedRowIndex)
            }
        },
        onRowsRendered: ({ rowInfo: { startIndex, stopIndex, overscanStopIndex } }) => {
            if (values.hasRemoteDataSource) {
                let loadFrom: number | null = null
                for (let i = startIndex; i < (stopIndex + overscanStopIndex) / 2; i++) {
                    if (!values.results[i]) {
                        loadFrom = i
                        break
                    }
                }
                if (loadFrom !== null) {
                    // The synthetic selected row (when present) sits before the remote block,
                    // so it shifts every remote row's display index by one — subtract it along
                    // with the local rows to recover the true remote offset.
                    const offset =
                        (loadFrom || startIndex) - values.localItems.count - (values.items.syntheticSelectedCount ?? 0)
                    actions.loadRemoteItems({ offset, limit: values.limit })
                }
            }
        },
        setActiveTab: ({ activeTab }) => {
            if (cache.lastActiveTab === activeTab) {
                return
            }
            cache.lastActiveTab = activeTab
            actions.resetPinnedRowState()
            actions.reconcilePinnedRowState()

            // A tab switch can cut short this list's in-flight (debounced) remote search before
            // it lands, leaving the cached results stale for the current query. Nothing else
            // re-fires the load, so the stale list surfaces as a false "No results" until a later
            // render or re-type. Reconcile here: if the cached remote query no longer matches the
            // active search, re-dispatch so switching to (or back to) a tab always reloads against
            // the current query. Skip when a load is already in flight — it reads the current
            // query at fetch time and settles correctly on its own.
            if (
                values.hasRemoteDataSource &&
                !values.remoteItemsLoading &&
                (values.remoteItems.searchQuery ?? '') !== values.searchQuery
            ) {
                actions.loadRemoteItems({ offset: 0, limit: values.limit })
            }
        },
        setSearchQuery: async () => {
            const searchQueryChanged = cache.lastSearchQuery !== values.searchQuery
            cache.lastSearchQuery = values.searchQuery

            if (searchQueryChanged) {
                actions.resetPinnedRowState()
            }
            if (values.hasRemoteDataSource) {
                actions.loadRemoteItems({ offset: 0, limit: values.limit })
            } else {
                if (props.autoSelectItem) {
                    actions.setIndex(0)
                }
                if (props.listGroupType !== TaxonomicFilterGroupType.SuggestedFilters) {
                    actions.infiniteListResultsReceived(props.listGroupType, values.localItems)
                }
            }
        },
        setIncludeStaleEvents: () => {
            const affectsThisTab =
                props.listGroupType === TaxonomicFilterGroupType.Events ||
                props.listGroupType === TaxonomicFilterGroupType.CustomEvents
            if (affectsThisTab && values.hasRemoteDataSource) {
                actions.loadRemoteItems({ offset: 0, limit: values.limit })
            }
        },
        togglePinnedRow: ({ rowIndex }) => {
            actions.setIndex(rowIndex)
        },
        moveUp: () => {
            const { index, totalListCount } = values
            actions.setIndex((index - 1 + totalListCount) % totalListCount)
        },
        moveDown: () => {
            const { index, totalListCount } = values
            actions.setIndex((index + 1) % totalListCount)
        },
        selectSelected: () => {
            if (values.isExpandableButtonSelected) {
                actions.expand()
            } else {
                const selectedItem = values.selectedItem
                const itemGroup = getItemGroup(selectedItem, values.taxonomicGroups, values.group)
                const isDisabledItem = selectedItem && itemGroup?.getIsDisabled?.(selectedItem)

                if (!isDisabledItem && itemGroup) {
                    const itemValue = selectedItem ? itemGroup.getValue?.(selectedItem) : null
                    actions.selectItem(itemGroup, itemValue ?? null, selectedItem, {
                        position: values.index,
                    })
                }
            }
        },
        loadRemoteItemsSuccess: ({ remoteItems }) => {
            actions.infiniteListResultsReceived(props.listGroupType, remoteItems)

            // A success ends the failure episode: the next failure for the same query is a
            // new episode and should capture again, not be deduped against the previous one.
            cache.lastFetchFailedDedupeKey = null

            const trimmedQuery = (remoteItems.searchQuery ?? '').trim()
            const queryReachedBackend = trimmedQuery.length >= values.minSearchQueryLength
            // Only fire on the tab the user is actually looking at — every list runs the same
            // search in parallel, so without this gate one keystroke can fire 4-8 empty events
            // from background tabs the user never sees, inflating the dead-end metric.
            if (
                values.isActiveTab &&
                trimmedQuery.length > 0 &&
                queryReachedBackend &&
                remoteItems.results.length === 0
            ) {
                const dedupeKey = `${props.listGroupType}::${trimmedQuery}`
                if (cache.lastEmptyResultDedupeKey !== dedupeKey) {
                    cache.lastEmptyResultDedupeKey = dedupeKey
                    posthog.capture('taxonomic filter empty result', {
                        surface: legacyTaxonomicSurface(
                            posthog.getFeatureFlag(FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN)
                        ),
                        groupType: props.listGroupType,
                        searchQuery: trimmedQuery,
                    })
                }
            }
        },
        remoteItemsFetchFailedForQuery: ({ searchQuery }) => {
            // Failures land on the same empty state as genuine no-matches, so without this
            // capture the "event exists but the backend blipped" case is invisible in prod.
            // Only count failures the user can actually see: the current query (a stale
            // out-of-order failure is rejected by `remoteResultsAreFresh` and never renders),
            // a real typed search (mount loads with an empty query are a different signal),
            // and the active tab — every list runs the search in parallel, and background-tab
            // failures the user never sees would inflate the metric.
            const trimmedQuery = searchQuery.trim()
            if (!values.isActiveTab || searchQuery !== values.searchQuery || trimmedQuery.length === 0) {
                return
            }
            const dedupeKey = `${props.listGroupType}::${trimmedQuery}`
            if (cache.lastFetchFailedDedupeKey !== dedupeKey) {
                cache.lastFetchFailedDedupeKey = dedupeKey
                posthog.capture('taxonomic filter fetch failed', {
                    surface: legacyTaxonomicSurface(
                        posthog.getFeatureFlag(FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN)
                    ),
                    groupType: props.listGroupType,
                    searchQuery: trimmedQuery,
                })
            }
        },
        infiniteListResultsReceived: () => {
            actions.reconcilePinnedRowState()
        },
        applyInitialPinnedRow: ({ rowIndex }) => {
            actions.setIndex(rowIndex)
        },
        expand: () => {
            actions.loadRemoteItems({ offset: values.index, limit: values.limit })
        },
        abortAnyRunningQuery: () => {
            // Remove any existing abort controller
            cache.disposables.dispose('abortController')

            // Add new abort controller
            cache.disposables.add(() => {
                const abortController = new AbortController()
                // Store reference in cache for the fetch operation to use
                cache.abortController = abortController
                return () => abortController.abort()
            }, 'abortController')
        },
    })),
    events(({ actions, values, props, cache }) => ({
        afterMount: () => {
            cache.lastActiveTab = values.activeTab
            cache.lastSearchQuery = values.searchQuery

            if (values.hasRemoteDataSource) {
                actions.loadRemoteItems({ offset: 0, limit: values.limit })
            } else if (values.groupType === props.listGroupType) {
                const { value, group, results } = values
                actions.setIndex(results.findIndex((r) => group?.getValue?.(r) === value))
            }

            actions.reconcilePinnedRowState()

            // Clean up all cache timers to prevent memory leaks
            cache.disposables.add(() => {
                return () => {
                    Object.values(apiCacheTimers).forEach((timerId) => {
                        window.clearTimeout(timerId)
                    })
                }
            }, 'apiCacheTimersCleanup')
        },
    })),

    // Note: API cache timers are automatically cleaned up by the disposables plugin (configured in afterMount)
])
