/**
 * Per-tab list state hook. Replaces `infiniteListLogic` for the new headless
 * `useTaxonomicFilter`. One instance per active TaxonomicFilterGroup.
 *
 * Owns:
 *   - `index` (keyboard highlight)
 *   - `isExpanded` (scoped → full-results toggle)
 *   - the merged `items` list (local Fuse search OR remote `useTaxonomicResource`)
 *   - rowCount / loading / empty-state derivations
 *
 * Does NOT own (delegated to the orchestrator):
 *   - the search query (passed in)
 *   - top-match aggregation across groups
 *   - the recent / pinned prefix injection on SuggestedFilters
 *   - keyboard nav across tabs
 *
 * Open follow-ups (not implemented in v1):
 *   - DataWarehouse pinned-row detail-pane state
 *   - search-latency telemetry (legacy emits `taxonomic filter search latency`
 *     from the list-results handler; the rebuild emits its own menu events)
 *   - the GroupNamesPrefix clickhouse fast path (still goes through generic
 *     endpoint fetcher; behaviour identical, just slower for large groups)
 */
import { useMemo, useState } from 'react'

import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import {
    isQuickFilterItem,
    ListStorage,
    QuickFilterItem,
    SimpleOption,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { floatRecentAndPinnedToTop, groupItemKey } from 'lib/components/TaxonomicFilter/utils/floatRecentPinned'
import { createFuse } from 'lib/utils/fuseSearch'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import { fetchTaxonomicListPage } from './fetchTaxonomicListPage'
import { useTaxonomicResource } from './useTaxonomicResource'

export const NO_ITEM_SELECTED = -1

const EMPTY_RESULTS: TaxonomicDefinitionTypes[] = []
const EMPTY_LIST_STORAGE: ListStorage = { results: EMPTY_RESULTS, searchQuery: '', count: 0 }

export interface UseGroupListInput {
    group: TaxonomicFilterGroup
    searchQuery: string
    /** Overrides group.logic-based local items. Provide from the orchestrator
     *  for groups whose source data lives in another kea logic. */
    localOverride?: TaxonomicDefinitionTypes[]
    /** Static options keyed by group type (e.g. Metadata, Wildcards). */
    optionsFromProp?: Partial<Record<TaxonomicFilterGroupType, SimpleOption[]>>
    /** When true, emits `is_numerical=true` to remote endpoints and filters
     *  numeric-only items locally for DataWarehousePersonProperties. */
    showNumericalPropsOnly?: boolean
    hideBehavioralCohorts?: boolean
    /** Exclude event definitions not seen within the staleness window (event /
     *  custom-event endpoints only). Mirrors legacy's default-on `exclude_stale`. */
    excludeStale?: boolean
    /** Override per-group minSearchQueryLength. */
    minSearchQueryLength?: number
    /** Pagination page size. */
    limit?: number
    /** Allow selecting events that haven't been captured yet. */
    allowNonCapturedEvents?: boolean
    /** Surface keyword shortcuts as QuickFilterItems alongside real results. */
    enableKeywordShortcuts?: boolean
    /** When true, disable the auto-select of first item on results refresh. */
    autoSelectItem?: boolean
    /** When true, the list initialises with index=0; otherwise index=NO_ITEM_SELECTED. */
    selectFirstItem?: boolean
    /** Set only when this is the filter's sole substantive group (no separate Recent/Pinned
     *  tabs lead the filter). Floats these recent (most-recent first) then pinned items to
     *  the top of the un-searched list. Mirrors legacy infiniteListLogic's `soleGroupValueKeyer`
     *  path. */
    promoteRecentItemsToTop?: TaxonomicDefinitionTypes[]
    promotePinnedItemsToTop?: TaxonomicDefinitionTypes[]
}

export interface UseGroupListResult {
    /** Combined items (local + remote + keyword shortcuts), with QuickFilterItems first when enabled. */
    items: TaxonomicDefinitionTypes[]
    /** items.length plus synthetic rows like the expand button. */
    rowCount: number
    /** Number of "real" results (excluding synthetic rows). */
    totalResultCount: number
    /** Currently highlighted row. NO_ITEM_SELECTED (-1) if no selection. */
    index: number
    setIndex: (index: number) => void
    moveUp: () => void
    moveDown: () => void
    /** Returns the item at a given index (or current index by default). */
    itemAtIndex: (index?: number) => TaxonomicDefinitionTypes | undefined

    isLoading: boolean
    isFetching: boolean
    needsMoreSearchCharacters: boolean
    hasRemoteDataSource: boolean
    showEmptyState: boolean
    showLoadingState: boolean
    showNonCapturedEventOption: boolean

    isExpandable: boolean
    isExpanded: boolean
    expand: () => void

    refetch: () => void
}

const DEFAULT_LIMIT = 100

export function useGroupList(input: UseGroupListInput): UseGroupListResult {
    const {
        group,
        searchQuery,
        localOverride,
        optionsFromProp,
        showNumericalPropsOnly = false,
        hideBehavioralCohorts = false,
        excludeStale = false,
        minSearchQueryLength: minSearchOverride,
        limit = DEFAULT_LIMIT,
        allowNonCapturedEvents = false,
        enableKeywordShortcuts = false,
        autoSelectItem = true,
        selectFirstItem = true,
        promoteRecentItemsToTop,
        promotePinnedItemsToTop,
    } = input

    const [isExpanded, setIsExpanded] = useState(false)
    const [index, setIndex] = useState<number>(
        selectFirstItem === false || autoSelectItem === false ? NO_ITEM_SELECTED : 0
    )

    // ---- Local data source --------------------------------------------------
    const rawLocalItems = useMemo<TaxonomicDefinitionTypes[] | null>(() => {
        if (localOverride !== undefined) {
            return localOverride
        }
        if (group.options) {
            return group.options as TaxonomicDefinitionTypes[]
        }
        if (optionsFromProp && optionsFromProp[group.type]) {
            return optionsFromProp[group.type] as TaxonomicDefinitionTypes[]
        }
        return null
    }, [localOverride, group, optionsFromProp])

    const filteredLocalItems = useMemo<TaxonomicDefinitionTypes[] | null>(() => {
        if (!rawLocalItems) {
            return null
        }
        if (showNumericalPropsOnly && group.type === TaxonomicFilterGroupType.DataWarehousePersonProperties) {
            return rawLocalItems.filter((item) => 'property_type' in item && (item as any).property_type === 'Numeric')
        }
        return rawLocalItems
    }, [rawLocalItems, showNumericalPropsOnly, group.type])

    const fuse = useMemo(() => {
        if (!filteredLocalItems) {
            return null
        }
        const haystack = filteredLocalItems.map((item) => {
            const name = group.getName?.(item) ?? ('name' in item ? (item as { name?: string }).name : '') ?? ''
            const posthogName = getCoreFilterDefinition(name, group.type)?.label
            const recentLabel =
                hasRecentContext(item) && item._recentContext.propertyFilter
                    ? formatPropertyLabel(item._recentContext.propertyFilter, {})
                    : undefined
            return { name, posthogName, recentLabel, item }
        })
        return createFuse(haystack, { keys: ['name', 'posthogName', 'recentLabel'], ignoreLocation: true })
    }, [filteredLocalItems, group])

    const localItems = useMemo<ListStorage>(() => {
        if (group.localItemsSearch) {
            const filtered = group.localItemsSearch(filteredLocalItems ?? [], searchQuery)
            return { results: filtered, count: filtered.length, searchQuery }
        }
        if (filteredLocalItems) {
            const results =
                searchQuery && fuse
                    ? fuse.search(searchQuery).map((r: any) => r.item.item as TaxonomicDefinitionTypes)
                    : filteredLocalItems
            return { results, count: results.length, searchQuery }
        }
        return EMPTY_LIST_STORAGE
    }, [group, filteredLocalItems, searchQuery, fuse])

    // ---- Remote data source -------------------------------------------------
    const hasRemoteDataSource = !!group.endpoint
    const minSearchQueryLength = minSearchOverride ?? group.minSearchQueryLength ?? 0
    const trimmedSearch = searchQuery.trim()
    const needsMoreSearchCharacters = minSearchQueryLength > 0 && trimmedSearch.length < minSearchQueryLength

    const remoteEnabled = hasRemoteDataSource && !needsMoreSearchCharacters

    // `clientFilterFirstPage` groups (e.g. Cohorts) pin the remote query to
    // the empty-search first page and let local Fuse handle keystroke
    // filtering — gives the same snappy feel as a local-only group while
    // still picking up server-side hidden/excluded filtering. The cache
    // key drops `searchQuery` so every keystroke hits the same entry.
    const clientFilter = !!group.clientFilterFirstPage
    const remoteSearchQuery = clientFilter ? '' : searchQuery

    const remoteKey = useMemo(
        () => [
            'taxonomic-list',
            group.type,
            group.endpoint,
            group.scopedEndpoint ?? null,
            isExpanded,
            remoteSearchQuery,
            limit,
            showNumericalPropsOnly,
            hideBehavioralCohorts,
            excludeStale,
        ],
        [
            group.type,
            group.endpoint,
            group.scopedEndpoint,
            isExpanded,
            remoteSearchQuery,
            limit,
            showNumericalPropsOnly,
            hideBehavioralCohorts,
            excludeStale,
        ]
    )

    const remote = useTaxonomicResource<ListStorage>(
        remoteKey,
        ({ signal }) =>
            fetchTaxonomicListPage({
                group,
                searchQuery: remoteSearchQuery,
                offset: 0,
                limit,
                isExpanded,
                showNumericalPropsOnly,
                hideBehavioralCohorts,
                excludeStale,
                signal,
            }),
        // Long staleTime for client-filtered groups — the cached first page
        // is the single source of truth for the whole typing session.
        // Cohort create/update should invalidate via `invalidateTaxonomicResource`
        // (TODO) so a fresh fetch picks up the new item.
        {
            enabled: remoteEnabled,
            staleTime: clientFilter ? 5 * 60_000 : 60_000,
            keepPreviousData: true,
        }
    )

    const remoteItemsRaw: ListStorage = remote.data ?? EMPTY_LIST_STORAGE

    // A `clientFilterFirstPage` group can only fuse what it cached — the
    // empty-search first page. When the server holds more rows than fit on
    // that page, local fuse silently misses every match outside it (e.g. a
    // team with >100 cohorts can't find cohort #137 by name). Once we learn
    // the dataset is bigger than one page, fall back to a real server search
    // for typed queries; the snappy local path still serves the common case
    // where the whole list fits in the first page.
    const firstPageIncomplete = clientFilter && remoteItemsRaw.count > remoteItemsRaw.results.length
    const serverSearchEnabled = firstPageIncomplete && !!trimmedSearch && !needsMoreSearchCharacters

    const serverSearchKey = useMemo(
        () => [
            'taxonomic-list-search',
            group.type,
            group.endpoint,
            group.scopedEndpoint ?? null,
            isExpanded,
            trimmedSearch,
            limit,
            showNumericalPropsOnly,
            hideBehavioralCohorts,
            excludeStale,
        ],
        [
            group.type,
            group.endpoint,
            group.scopedEndpoint,
            isExpanded,
            trimmedSearch,
            limit,
            showNumericalPropsOnly,
            hideBehavioralCohorts,
            excludeStale,
        ]
    )

    const serverSearch = useTaxonomicResource<ListStorage>(
        serverSearchKey,
        ({ signal }) =>
            fetchTaxonomicListPage({
                group,
                searchQuery: trimmedSearch,
                offset: 0,
                limit,
                isExpanded,
                showNumericalPropsOnly,
                hideBehavioralCohorts,
                excludeStale,
                signal,
            }),
        { enabled: serverSearchEnabled, staleTime: 60_000, keepPreviousData: true }
    )

    // Per-fetch Fuse index over the cached first page. Built lazily on
    // first non-empty query, then re-used across keystrokes until the
    // page changes (refetch / invalidate).
    const remoteFuse = useMemo(() => {
        if (!clientFilter || remoteItemsRaw.results.length === 0) {
            return null
        }
        const haystack = remoteItemsRaw.results.map((item) => {
            const name = group.getName?.(item) ?? ('name' in item ? (item as { name?: string }).name : '') ?? ''
            const posthogName = getCoreFilterDefinition(name, group.type)?.label
            return { name, posthogName, item }
        })
        return createFuse(haystack, { keys: ['name', 'posthogName'], ignoreLocation: true })
    }, [clientFilter, remoteItemsRaw, group])

    const remoteItems: ListStorage = useMemo(() => {
        if (!clientFilter || !trimmedSearch) {
            return remoteItemsRaw
        }
        // Dataset bigger than one page: the server search is authoritative.
        // Show the local fuse of the cached first page until it resolves so
        // there's no blank flash, then swap in the full server result.
        if (serverSearchEnabled && serverSearch.data) {
            return serverSearch.data
        }
        const filtered = remoteFuse
            ? (remoteFuse.search(trimmedSearch).map((r: any) => r.item.item) as TaxonomicDefinitionTypes[])
            : []
        return { results: filtered, searchQuery, count: filtered.length }
    }, [clientFilter, trimmedSearch, remoteItemsRaw, remoteFuse, searchQuery, serverSearchEnabled, serverSearch.data])

    // ---- Combined items + keyword shortcuts --------------------------------
    const keywordShortcuts: QuickFilterItem[] = useMemo(() => {
        if (!enableKeywordShortcuts || !group.keywordShortcuts || !trimmedSearch) {
            return []
        }
        return group.keywordShortcuts(searchQuery)
    }, [enableKeywordShortcuts, group, searchQuery, trimmedSearch])

    const items: TaxonomicDefinitionTypes[] = useMemo(() => {
        const merged: TaxonomicDefinitionTypes[] = []
        merged.push(...keywordShortcuts)
        if (localItems.results.length > 0) {
            merged.push(...localItems.results)
        }
        if (remoteItems.results.length > 0) {
            merged.push(...remoteItems.results)
        }
        // Sole substantive group: float its own recent/pinned items to the top of the
        // un-searched list (keyword shortcuts only appear while searching, so they're
        // never displaced). Mirrors legacy infiniteListLogic's `soleGroupValueKeyer` path.
        if (!trimmedSearch && (promoteRecentItemsToTop?.length || promotePinnedItemsToTop?.length)) {
            const keyOf = (item: TaxonomicDefinitionTypes): string | null =>
                groupItemKey(group.type, group.getValue?.(item) ?? null)
            return floatRecentAndPinnedToTop(
                merged,
                keyOf,
                promoteRecentItemsToTop || [],
                promotePinnedItemsToTop || []
            ) as TaxonomicDefinitionTypes[]
        }
        return merged
    }, [
        keywordShortcuts,
        localItems,
        remoteItems,
        trimmedSearch,
        promoteRecentItemsToTop,
        promotePinnedItemsToTop,
        group,
    ])

    const isExpandable = !!(
        group.endpoint &&
        group.scopedEndpoint &&
        remoteItems.expandedCount &&
        remoteItems.expandedCount > remoteItems.count
    )
    // Match legacy semantics: `count` is the API-reported total + local pool
    // size + keyword shortcuts, NOT the loaded array length. Without this,
    // remote groups with paginated results under-report (e.g. Event properties
    // shows 100 instead of 310). `rowCount` stays length-based since it drives
    // virtualisation.
    const totalResultCount = keywordShortcuts.length + localItems.count + (hasRemoteDataSource ? remoteItems.count : 0)
    const rowCount = items.length + (isExpandable ? 1 : 0)

    // ---- Loading / empty state ---------------------------------------------
    // Fold the server-search fallback into the busy flags so the skeleton
    // (not "no results") shows while it's in flight on a >1-page dataset.
    const isLoading = remote.isLoading || (serverSearchEnabled && serverSearch.isLoading)
    const isFetching = remote.isFetching || (serverSearchEnabled && serverSearch.isFetching)

    const showNonCapturedEventOption = useMemo(() => {
        if (!allowNonCapturedEvents) {
            return false
        }
        if (group.type !== TaxonomicFilterGroupType.Events && group.type !== TaxonomicFilterGroupType.CustomEvents) {
            return false
        }
        if (!trimmedSearch || isLoading) {
            return false
        }
        const realResults = items.filter((item) => !isQuickFilterItem(item))
        return realResults.length === 0
    }, [allowNonCapturedEvents, group.type, trimmedSearch, isLoading, items])

    // Empty / loading state checks read array length, not the API-reported
    // total — a remote tab can have count > 0 while still loading its first
    // page, and we don't want to flash an empty state during that window.
    const showEmptyState =
        (items.length === 0 && !isLoading && (!!searchQuery || !hasRemoteDataSource) && !showNonCapturedEventOption) ||
        needsMoreSearchCharacters

    const showLoadingState = isLoading && items.length === 0

    // ---- Index / keyboard nav ----------------------------------------------
    const moveUp = (): void => {
        if (rowCount === 0) {
            return
        }
        setIndex((cur) => (cur - 1 + rowCount) % rowCount)
    }

    const moveDown = (): void => {
        if (rowCount === 0) {
            return
        }
        setIndex((cur) => (cur + 1 + rowCount) % rowCount)
    }

    const itemAtIndex = (i: number = index): TaxonomicDefinitionTypes | undefined => {
        if (i < 0 || i >= items.length) {
            return undefined
        }
        return items[i]
    }

    const expand = (): void => {
        setIsExpanded(true)
    }

    return {
        items,
        rowCount,
        totalResultCount,
        index,
        setIndex,
        moveUp,
        moveDown,
        itemAtIndex,
        isLoading,
        isFetching,
        needsMoreSearchCharacters,
        hasRemoteDataSource,
        showEmptyState,
        showLoadingState,
        showNonCapturedEventOption,
        isExpandable,
        isExpanded,
        expand,
        refetch: () => {
            remote.refetch()
        },
    }
}
