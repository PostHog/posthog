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
 *   - performance instrumentation (`captureTimeToSeeData`)
 *   - the GroupNamesPrefix clickhouse fast path (still goes through generic
 *     endpoint fetcher; behaviour identical, just slower for large groups)
 */
import { useMemo, useRef, useState } from 'react'

import {
    isQuickFilterItem,
    ListStorage,
    QuickFilterItem,
    SimpleOption,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
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
    /** Override per-group minSearchQueryLength. */
    minSearchQueryLength?: number
    /** Pagination page size. */
    limit?: number
    /** Allow selecting events that haven't been captured yet. */
    allowNonCapturedEvents?: boolean
    /** Surface keyword shortcuts as QuickFilterItems alongside real results. */
    enableKeywordShortcuts?: boolean
    /** When false, disable the auto-select of first item on results refresh. */
    autoSelectItem?: boolean
    /** When true, the list initialises with index=0; otherwise index=NO_ITEM_SELECTED. */
    selectFirstItem?: boolean
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
        minSearchQueryLength: minSearchOverride,
        limit = DEFAULT_LIMIT,
        allowNonCapturedEvents = false,
        enableKeywordShortcuts = false,
        autoSelectItem = true,
        selectFirstItem = true,
    } = input

    const [isExpanded, setIsExpanded] = useState(false)
    const initialIndex = selectFirstItem === false || autoSelectItem === false ? NO_ITEM_SELECTED : 0
    const [index, setIndex] = useState<number>(initialIndex)

    // Reset the keyboard highlight whenever the search query changes so the cursor
    // never points past the end of a freshly-narrowed results list — otherwise
    // itemAtIndex(staleIndex) returns undefined and selectSelected() falls through
    // to onEnter(searchQuery), creating a new event/expression instead of selecting
    // the highlighted row.
    const prevSearchRef = useRef(searchQuery)
    if (prevSearchRef.current !== searchQuery) {
        prevSearchRef.current = searchQuery
        setIndex(initialIndex)
    }

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
            return { name, posthogName, recentLabel: undefined, item }
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

    const remoteKey = useMemo(
        () => [
            'taxonomic-list',
            group.type,
            group.endpoint,
            group.scopedEndpoint ?? null,
            isExpanded,
            searchQuery,
            limit,
            showNumericalPropsOnly,
            hideBehavioralCohorts,
            group.excludedProperties ?? null,
            group.propertyAllowList ?? null,
        ],
        [
            group.type,
            group.endpoint,
            group.scopedEndpoint,
            isExpanded,
            searchQuery,
            limit,
            showNumericalPropsOnly,
            hideBehavioralCohorts,
            group.excludedProperties,
            group.propertyAllowList,
        ]
    )

    const remote = useTaxonomicResource<ListStorage>(
        remoteKey,
        ({ signal }) =>
            fetchTaxonomicListPage({
                group,
                searchQuery,
                offset: 0,
                limit,
                isExpanded,
                showNumericalPropsOnly,
                hideBehavioralCohorts,
                signal,
            }),
        { enabled: remoteEnabled, staleTime: 60_000, keepPreviousData: true }
    )

    const remoteItems: ListStorage = remote.data ?? EMPTY_LIST_STORAGE

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
        return merged
    }, [keywordShortcuts, localItems, remoteItems])

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
    const isLoading = remote.isLoading
    const isFetching = remote.isFetching

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
