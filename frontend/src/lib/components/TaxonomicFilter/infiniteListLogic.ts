import Fuse from 'fuse.js'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl } from 'kea-router'
import api from 'lib/api'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    InfiniteListLogicProps,
    ListFuse,
    ListStorage,
    LoaderOptions,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
} from 'lib/components/TaxonomicFilter/types'
import { EVENT_PROPERTY_DEFINITIONS_PER_PAGE } from 'lib/constants'
import { getCoreFilterDefinition } from 'lib/taxonomy'
import { RenderedRows } from 'react-virtualized/dist/es/List'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { CohortType, EventDefinition } from '~/types'

import { teamLogic } from '../../../scenes/teamLogic'
import { captureTimeToSeeData } from '../../internalMetrics'
import type { infiniteListLogicType } from './infiniteListLogicType'

/*
 by default the pop-up starts open for the first item in the list
 this can be used with actions.setIndex to allow a caller to override that
 */
export const NO_ITEM_SELECTED = -1

const createEmptyListStorage = (searchQuery = '', first = false): ListStorage => ({
    results: [],
    searchQuery,
    count: 0,
    first,
})

// simple cache with a setTimeout expiry
const API_CACHE_TIMEOUT = 60000

async function fetchCachedListResponse(path: string, searchParams: Record<string, any>): Promise<ListStorage> {
    const url = combineUrl(path, searchParams).url
    const cacheKey = `taxonomic_filter_${url}`

    // Try localStorage first
    const cachedData = localStorage.getItem(cacheKey)
    if (cachedData) {
        const { data, timestamp } = JSON.parse(cachedData)
        if (Date.now() - timestamp < API_CACHE_TIMEOUT) {
            return data
        }
    }

    // If not in localStorage or expired, fetch from API
    const response = await api.get(url)

    // Cache in localStorage
    localStorage.setItem(
        cacheKey,
        JSON.stringify({
            data: response,
            timestamp: Date.now(),
        })
    )

    return response
}

// Only clear specific cache entries instead of all
function invalidateCache(itemName: string | null | undefined): void {
    if (!itemName) {
        return
    }
    Object.keys(localStorage).forEach((key) => {
        if (key.startsWith('taxonomic_filter_') && key.includes(itemName)) {
            localStorage.removeItem(key)
        }
    })
}

export const infiniteListLogic = kea<infiniteListLogicType>([
    props({ showNumericalPropsOnly: false } as InfiniteListLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}-${props.listGroupType}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'infiniteListLogic', key]),
    connect((props: InfiniteListLogicProps) => ({
        values: [
            taxonomicFilterLogic(props),
            ['searchQuery', 'value', 'groupType', 'taxonomicGroups'],
            teamLogic,
            ['currentTeamId'],
            featureFlagsLogic,
            ['featureFlags'],
        ],
        actions: [taxonomicFilterLogic(props), ['setSearchQuery', 'selectItem', 'infiniteListResultsReceived']],
    })),
    actions({
        selectSelected: true,
        moveUp: true,
        moveDown: true,
        setIndex: (index: number) => ({ index }),
        setLimit: (limit: number) => ({ limit }),
        onRowsRendered: (rowInfo: RenderedRows) => ({ rowInfo }),
        loadRemoteItems: (options: LoaderOptions) => options,
        updateRemoteItem: (item: TaxonomicDefinitionTypes) => ({ item }),
        expand: true,
        abortAnyRunningQuery: true,
        loadMore: true,
    }),
    loaders(({ actions, values, cache, props }) => ({
        remoteItems: [
            createEmptyListStorage('', true),
            {
                loadRemoteItems: async ({ offset, limit }, breakpoint) => {
                    // avoid the 150ms delay on first load
                    if (!values.remoteItems.first) {
                        await breakpoint(500)
                    } else {
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
                    } = values

                    if (!remoteEndpoint) {
                        return createEmptyListStorage(searchQuery)
                    }

                    const searchParams = {
                        [`${values.group?.searchAlias || 'search'}`]: searchQuery,
                        limit,
                        offset,
                        excluded_properties: JSON.stringify(excludedProperties),
                        properties: propertyAllowList ? propertyAllowList.join(',') : undefined,
                        ...(props.hideBehavioralCohorts ? { hide_behavioral_cohorts: 'true' } : {}),
                    }

                    const start = performance.now()
                    actions.abortAnyRunningQuery()

                    const response = await fetchCachedListResponse(
                        scopedRemoteEndpoint && !isExpanded ? scopedRemoteEndpoint : remoteEndpoint,
                        searchParams
                    )
                    breakpoint()

                    const queryChanged = values.remoteItems.searchQuery !== values.searchQuery

                    await captureTimeToSeeData(values.currentTeamId, {
                        type: 'properties_load',
                        context: 'filters',
                        action: listGroupType,
                        primary_interaction_id: '',
                        status: 'success',
                        time_to_see_data_ms: Math.floor(performance.now() - start),
                        api_response_bytes: 0,
                    })
                    cache.abortController = null

                    const results = queryChanged
                        ? response.results
                        : [...(offset === 0 ? [] : values.remoteItems.results), ...response.results]

                    return {
                        results,
                        searchQuery: values.searchQuery,
                        queryChanged,
                        count: response.count,
                        total_count: response.total_count,
                        has_more: response.has_more,
                        expandedCount: response.expandedCount,
                    }
                },
                updateRemoteItem: ({ item }) => {
                    // Only invalidate cache for this specific item
                    invalidateCache(item.name)
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
            (props.selectFirstItem === false ? NO_ITEM_SELECTED : 0) as number,
            {
                setIndex: (_, { index }) => index,
                loadRemoteItemsSuccess: (state, { remoteItems }) => (remoteItems.queryChanged ? 0 : state),
            },
        ],
        showPopover: [props.popoverEnabled !== false, {}],
        limit: [
            EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
            {
                setLimit: (_, { limit }) => limit,
            },
        ],
        startIndex: [0, { onRowsRendered: (_, { rowInfo: { startIndex } }) => startIndex }],
        stopIndex: [0, { onRowsRendered: (_, { rowInfo: { stopIndex } }) => stopIndex }],
        isExpanded: [false, { expand: () => true }],
        totalCount: [
            0,
            {
                loadRemoteItemsSuccess: (_, { remoteItems }) => remoteItems.total_count || remoteItems.count || 0,
            },
        ],
        hasMore: [
            true,
            {
                loadRemoteItemsSuccess: (_, { remoteItems }) =>
                    remoteItems.has_more ||
                    (remoteItems.results.length > 0 && remoteItems.total_count > remoteItems.results.length),
            },
        ],
    })),
    selectors({
        listGroupType: [() => [(_, props) => props.listGroupType], (listGroupType) => listGroupType],
        isLoading: [(s) => [s.remoteItemsLoading], (remoteItemsLoading) => remoteItemsLoading],
        group: [
            (s) => [s.listGroupType, s.taxonomicGroups],
            (listGroupType, taxonomicGroups): TaxonomicFilterGroup =>
                taxonomicGroups.find((g) => g.type === listGroupType) as TaxonomicFilterGroup,
        ],
        remoteEndpoint: [(s) => [s.group], (group) => group?.endpoint || null],
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
        rawLocalItems: [
            (selectors) => [
                (state, props: InfiniteListLogicProps) => {
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
            ],
            (rawLocalItems: (EventDefinition | CohortType)[]) => rawLocalItems,
        ],
        fuse: [
            (s) => [s.rawLocalItems, s.group],
            (rawLocalItems, group): ListFuse => {
                // maps e.g. "selector" to its display value "CSS Selector"
                // so a search of "css" matches something
                function asPostHogName(
                    group: TaxonomicFilterGroup,
                    item: EventDefinition | CohortType
                ): string | undefined {
                    return group ? getCoreFilterDefinition(group.getName?.(item), group.type)?.label : undefined
                }

                const haystack = (rawLocalItems || []).map((item) => ({
                    name: group?.getName?.(item) || '',
                    posthogName: asPostHogName(group, item),
                    item: item,
                }))

                return new Fuse(haystack, {
                    keys: ['name', 'posthogName'],
                    threshold: 0.3,
                })
            },
        ],
        localItems: [
            (s) => [s.rawLocalItems, s.searchQuery, s.fuse],
            (rawLocalItems, searchQuery, fuse): ListStorage => {
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
        items: [
            (s, p) => [s.remoteItems, s.localItems, p.showNumericalPropsOnly ?? (() => false)],
            (remoteItems, localItems, showNumericalPropsOnly) => {
                const results = [...localItems.results, ...remoteItems.results].filter((n) => {
                    if (!showNumericalPropsOnly) {
                        return true
                    }

                    if ('is_numerical' in n) {
                        return !!n.is_numerical
                    }

                    if ('property_type' in n) {
                        const property_type = n.property_type as string // Data warehouse props dont conform to PropertyType for some reason
                        return property_type === 'Integer' || property_type === 'Float'
                    }

                    return true
                })

                return {
                    results,
                    count: results.length,
                    searchQuery: localItems.searchQuery,
                    expandedCount: remoteItems.expandedCount,
                    queryChanged: remoteItems.queryChanged,
                    first: localItems.first && remoteItems.first,
                }
            },
        ],
        totalResultCount: [(s) => [s.totalCount], (totalCount) => totalCount],
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
        selectedItem: [
            (s) => [s.index, s.items],
            (index, items): TaxonomicDefinitionTypes | undefined => (index >= 0 ? items.results[index] : undefined),
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
                    const offset = (loadFrom || startIndex) - values.localItems.count
                    actions.loadRemoteItems({ offset, limit: values.limit })
                }
            }
        },
        setSearchQuery: async () => {
            if (values.hasRemoteDataSource) {
                actions.loadRemoteItems({ offset: 0, limit: values.limit })
            } else {
                actions.setIndex(0)
            }
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
                actions.selectItem(values.group, values.selectedItemValue, values.selectedItem)
            }
        },
        loadRemoteItemsSuccess: ({ remoteItems }) => {
            actions.infiniteListResultsReceived(props.listGroupType, remoteItems)
        },
        expand: () => {
            if (values.hasMore && !values.isLoading) {
                actions.loadRemoteItems({
                    offset: values.results.length,
                    limit: values.limit,
                })
            }
        },
        abortAnyRunningQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
            }
            cache.abortController = new AbortController()
        },
    })),
    events(({ actions, values, props }) => ({
        afterMount: () => {
            if (values.hasRemoteDataSource) {
                actions.loadRemoteItems({ offset: 0, limit: values.limit })
            } else if (values.groupType === props.listGroupType) {
                const { value, group, results } = values
                actions.setIndex(results.findIndex((r) => group?.getValue?.(r) === value))
            }
        },
    })),
])
