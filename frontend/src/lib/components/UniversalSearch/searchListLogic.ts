import { kea } from 'kea'
import { combineUrl } from 'kea-router'
import api from 'lib/api'
import { RenderedRows } from 'react-virtualized/dist/es/List'
import { CohortType, EventDefinition } from '~/types'
import Fuse from 'fuse.js'

import { ListFuse, LoaderOptions } from 'lib/components/TaxonomicFilter/types'
import {
    SearchDefinitionTypes,
    SearchListLogicProps,
    UniversalSearchGroup,
    ListStorage,
} from 'lib/components/UniversalSearch/types'
import { universalSearchLogic } from './universalSearchLogic'

import { searchListLogicType } from './searchListLogicType'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
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
const apiCache: Record<string, ListStorage> = {}
const apiCacheTimers: Record<string, number> = {}

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

export const searchListLogic = kea<searchListLogicType>({
    path: (key) => ['lib', 'components', 'UniversalSearch', 'searchListLogic', key],
    props: {} as SearchListLogicProps,

    key: (props) => `${props.universalSearchLogicKey}-${props.listGroupType}`,

    connect: (props: SearchListLogicProps) => ({
        // TODO: had to connect FF to get the model loaded for filtering
        values: [
            universalSearchLogic(props),
            ['searchQuery', 'value', 'groupType', 'searchGroups'],
            featureFlagsLogic,
            ['featureFlags'],
            experimentsLogic,
            ['experiments'],
            pluginsLogic,
            ['plugins'],
        ],
        actions: [universalSearchLogic(props), ['setSearchQuery', 'selectItem', 'searchListResultsReceived']],
    }),

    actions: {
        selectSelected: true,
        moveUp: true,
        moveDown: true,
        setIndex: (index: number) => ({ index }),
        setLimit: (limit: number) => ({ limit }),
        onRowsRendered: (rowInfo: RenderedRows) => ({ rowInfo }),
        loadRemoteItems: (options: LoaderOptions) => options,
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

                    const { remoteEndpoint, searchQuery } = values

                    if (!remoteEndpoint) {
                        // should not have been here in the first place!
                        return createEmptyListStorage(searchQuery)
                    }

                    const searchParams = {
                        [`${values.group?.searchAlias || 'search'}`]: searchQuery,
                        limit,
                        offset,
                    }

                    const response = await fetchCachedListResponse(remoteEndpoint, searchParams)
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
                        count: response.count || (response.results || []).length,
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
            const { index, totalResultCount } = values
            actions.setIndex((index - 1 + totalResultCount) % totalResultCount)
        },
        moveDown: () => {
            const { index, totalResultCount } = values
            actions.setIndex((index + 1) % totalResultCount)
        },
        selectSelected: () => {
            actions.selectItem(values.group, values.selectedItemValue, values.selectedItem)
        },
        loadRemoteItemsSuccess: ({ remoteItems }) => {
            actions.searchListResultsReceived(props.listGroupType, remoteItems)
        },
    }),

    selectors: {
        listGroupType: [() => [(_, props) => props.listGroupType], (listGroupType) => listGroupType],
        isLoading: [(s) => [s.remoteItemsLoading], (remoteItemsLoading) => remoteItemsLoading],
        group: [
            (s) => [s.listGroupType, s.searchGroups],
            (listGroupType, searchGroups): UniversalSearchGroup =>
                searchGroups.find((g) => g.type === listGroupType) as UniversalSearchGroup,
        ],
        remoteEndpoint: [(s) => [s.group], (group) => group?.endpoint || null],
        isRemoteDataSource: [(s) => [s.remoteEndpoint], (remoteEndpoint) => !!remoteEndpoint],
        rawLocalItems: [
            (selectors) => [
                (state, props) => {
                    const searchGroups = selectors.searchGroups(state)
                    const group = searchGroups.find((g) => g.type === props.listGroupType)
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
        results: [(s) => [s.items], (items) => items.results],
        selectedItem: [
            (s) => [s.index, s.items],
            (index, items): SearchDefinitionTypes | undefined => (index >= 0 ? items.results[index] : undefined),
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
