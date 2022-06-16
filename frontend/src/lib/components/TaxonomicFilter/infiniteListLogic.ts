import { kea } from 'kea'
import { combineUrl } from 'kea-router'
import api from 'lib/api'
import { RenderedRows } from 'react-virtualized/dist/es/List'
import type { infiniteListLogicType } from './infiniteListLogicType'
import { CohortType, EventDefinition } from '~/types'
import Fuse from 'fuse.js'
import {
    InfiniteListLogicProps,
    ListFuse,
    ListStorage,
    LoaderOptions,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
} from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

/*
 by default the pop-up starts open for the first item in the list
 this can be used with actions.setIndex to allow a caller to override that
 */
export const NO_ITEM_SELECTED = -1

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

async function fetchCachedListResponse(path: string, searchParams: Record<string, any>): Promise<ListStorage> {
    const url = combineUrl(path, searchParams).url
    let response
    if (apiCache[url]) {
        response = apiCache[url]
    } else {
        response = await api.get(url)
        apiCache[url] = response
        apiCacheTimers[url] = window.setTimeout(() => {
            delete apiCache[url]
            delete apiCacheTimers[url]
        }, API_CACHE_TIMEOUT)
    }
    return response
}

export const infiniteListLogic = kea<infiniteListLogicType>({
    path: (key) => ['lib', 'components', 'TaxonomicFilter', 'infiniteListLogic', key],
    props: {} as InfiniteListLogicProps,

    key: (props) => `${props.taxonomicFilterLogicKey}-${props.listGroupType}`,

    connect: (props: InfiniteListLogicProps) => ({
        values: [
            taxonomicFilterLogic(props),
            ['searchQuery', 'value', 'groupType', 'taxonomicGroups'],
            featureFlagsLogic,
            ['featureFlags'],
        ],
        actions: [taxonomicFilterLogic(props), ['setSearchQuery', 'selectItem', 'infiniteListResultsReceived']],
    }),

    actions: {
        selectSelected: true,
        moveUp: true,
        moveDown: true,
        setIndex: (index: number) => ({ index }),
        setLimit: (limit: number) => ({ limit }),
        onRowsRendered: (rowInfo: RenderedRows) => ({ rowInfo }),
        loadRemoteItems: (options: LoaderOptions) => options,
        updateRemoteItem: (item: TaxonomicDefinitionTypes) => ({ item }),
        expand: true,
    },

    reducers: ({ props }) => ({
        index: [
            (props.selectFirstItem === false ? NO_ITEM_SELECTED : 0) as number,
            {
                setIndex: (_, { index }) => index,
                loadRemoteItemsSuccess: (state, { remoteItems }) => (remoteItems.queryChanged ? 0 : state),
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
    }),

    loaders: ({ values }) => ({
        remoteItems: [
            createEmptyListStorage('', true),
            {
                loadRemoteItems: async ({ offset, limit }, breakpoint) => {
                    // avoid the 150ms delay on first load
                    if (!values.remoteItems.first) {
                        await breakpoint(150)
                    } else {
                        // These connected values below might be read before they are available due to circular logic mounting.
                        // Adding a slight delay (breakpoint) fixes this.
                        await breakpoint(1)
                    }

                    const { isExpanded, remoteEndpoint, scopedRemoteEndpoint, searchQuery, excludedProperties } = values

                    if (!remoteEndpoint) {
                        // should not have been here in the first place!
                        return createEmptyListStorage(searchQuery)
                    }

                    const searchParams = {
                        [`${values.group?.searchAlias || 'search'}`]: searchQuery,
                        limit,
                        offset,
                        excluded_properties: JSON.stringify(excludedProperties),
                    }

                    const [response, expandedCountResponse] = await Promise.all([
                        // get the list of results
                        fetchCachedListResponse(
                            scopedRemoteEndpoint && !isExpanded ? scopedRemoteEndpoint : remoteEndpoint,
                            searchParams
                        ),
                        // if this is an unexpanded scoped list, get the count for the normafull list
                        scopedRemoteEndpoint && !isExpanded
                            ? fetchCachedListResponse(remoteEndpoint, {
                                  ...searchParams,
                                  limit: 1,
                                  offset: 0,
                              })
                            : null,
                    ])
                    breakpoint()

                    const queryChanged = values.items.searchQuery !== values.searchQuery

                    return {
                        results: appendAtIndex(
                            queryChanged ? [] : values.items.results,
                            response.results || response,
                            offset
                        ),
                        searchQuery: values.searchQuery,
                        queryChanged,
                        count:
                            response.count ||
                            (Array.isArray(response) ? response.length : 0) ||
                            (response.results || []).length,
                        expandedCount: expandedCountResponse?.count,
                    }
                },
                updateRemoteItem: ({ item }) => {
                    // On updating item, invalidate cache
                    apiCache = {}
                    apiCacheTimers = {}
                    return {
                        ...values.remoteItems,
                        results: values.remoteItems.results.map((i) => (i.name === item.name ? item : i)),
                    }
                },
            },
        ],
    }),

    listeners: ({ values, actions, props }) => ({
        onRowsRendered: ({ rowInfo: { startIndex, stopIndex, overscanStopIndex } }) => {
            if (values.isRemoteDataSource) {
                let loadFrom: number | null = null
                for (let i = startIndex; i < (stopIndex + overscanStopIndex) / 2; i++) {
                    if (!values.results[i]) {
                        loadFrom = i
                        break
                    }
                }
                if (loadFrom !== null) {
                    actions.loadRemoteItems({ offset: loadFrom || startIndex, limit: values.limit })
                }
            }
        },
        setSearchQuery: () => {
            if (values.isRemoteDataSource) {
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
            actions.loadRemoteItems({ offset: values.index, limit: values.limit })
        },
    }),

    selectors: {
        listGroupType: [() => [(_, props) => props.listGroupType], (listGroupType) => listGroupType],
        isLoading: [(s) => [s.remoteItemsLoading], (remoteItemsLoading) => remoteItemsLoading],
        group: [
            (s) => [s.listGroupType, s.taxonomicGroups],
            (listGroupType, taxonomicGroups): TaxonomicFilterGroup =>
                taxonomicGroups.find((g) => g.type === listGroupType) as TaxonomicFilterGroup,
        ],
        remoteEndpoint: [(s) => [s.group], (group) => group?.endpoint || null],
        excludedProperties: [(s) => [s.group], (group) => group?.excludedProperties],
        scopedRemoteEndpoint: [(s) => [s.group], (group) => group?.scopedEndpoint || null],
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
        isRemoteDataSource: [(s) => [s.remoteEndpoint], (remoteEndpoint) => !!remoteEndpoint],
        rawLocalItems: [
            (selectors) => [
                (state, props) => {
                    const taxonomicGroups = selectors.taxonomicGroups(state)
                    const group = taxonomicGroups.find((g) => g.type === props.listGroupType)
                    if (group?.logic && group?.value) {
                        return group.logic.selectors[group.value]?.(state) || null
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
            (rawLocalItems, group): ListFuse =>
                new Fuse(
                    (rawLocalItems || []).map((item) => ({
                        name: group?.getName?.(item) || '',
                        item: item,
                    })),
                    {
                        keys: ['name'],
                        threshold: 0.3,
                    }
                ),
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
            (s) => [s.isRemoteDataSource, s.remoteItems, s.localItems],
            (isRemoteDataSource, remoteItems, localItems) => (isRemoteDataSource ? remoteItems : localItems),
        ],
        totalResultCount: [(s) => [s.items], (items) => items.count || 0],
        totalExtraCount: [(s) => [s.isExpandable], (isExpandable) => (isExpandable ? 1 : 0)],
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
    },

    events: ({ actions, values, props }) => ({
        afterMount: () => {
            if (values.isRemoteDataSource) {
                actions.loadRemoteItems({ offset: 0, limit: values.limit })
            } else if (values.groupType === props.listGroupType) {
                const { value, group, results } = values
                actions.setIndex(results.findIndex((r) => group?.getValue?.(r) === value))
            }
        },
    }),
})
