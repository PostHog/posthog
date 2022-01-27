import { kea } from 'kea'
import { combineUrl } from 'kea-router'
import api from 'lib/api'
import { RenderedRows } from 'react-virtualized/dist/es/List'
import { EventDefinitionStorage } from '~/models/eventDefinitionsModel'
import { infiniteListLogicType } from './infiniteListLogicType'
import { CohortType, EventDefinition } from '~/types'
import Fuse from 'fuse.js'
import {
    InfiniteListLogicProps,
    ListFuse,
    ListStorage,
    LoaderOptions,
    TaxonomicFilterGroup,
} from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'

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
const apiCache: Record<string, EventDefinitionStorage> = {}
const apiCacheTimers: Record<string, number> = {}

export const infiniteListLogic = kea<infiniteListLogicType>({
    path: (key) => ['lib', 'components', 'TaxonomicFilter', 'infiniteListLogic', key],
    props: {} as InfiniteListLogicProps,

    key: (props) => `${props.taxonomicFilterLogicKey}-${props.listGroupType}`,

    connect: (props: InfiniteListLogicProps) => ({
        values: [taxonomicFilterLogic(props), ['searchQuery', 'value', 'groupType', 'taxonomicGroups']],
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
    },

    reducers: {
        index: [
            0 as number,
            {
                setIndex: (_, { index }) => index,
                loadRemoteItemsSuccess: (state, { remoteItems }) => (remoteItems.queryChanged ? 0 : state),
            },
        ],
        limit: [
            100,
            {
                setLimit: (_, { limit }) => limit,
            },
        ],
        startIndex: [0, { onRowsRendered: (_, { rowInfo: { startIndex } }) => startIndex }],
        stopIndex: [0, { onRowsRendered: (_, { rowInfo: { stopIndex } }) => stopIndex }],
    },

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

                    const url = combineUrl(remoteEndpoint, {
                        [`${values.group?.searchAlias || 'search'}`]: searchQuery,
                        limit,
                        offset,
                    }).url

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
                        breakpoint()
                    }

                    const queryChanged = values.items.searchQuery !== values.searchQuery

                    return {
                        results: appendAtIndex(
                            queryChanged ? [] : values.items.results,
                            response.results || response,
                            offset
                        ),
                        searchQuery: values.searchQuery,
                        queryChanged,
                        count: response.count || response.length || 0,
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
            const { index, totalCount } = values
            actions.setIndex((index - 1 + totalCount) % totalCount)
        },
        moveDown: () => {
            const { index, totalCount } = values
            actions.setIndex((index + 1) % totalCount)
        },
        selectSelected: () => {
            actions.selectItem(values.group, values.selectedItemValue, values.selectedItem)
        },
        loadRemoteItemsSuccess: ({ remoteItems }) => {
            actions.infiniteListResultsReceived(props.listGroupType, remoteItems)
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
        totalCount: [(s) => [s.items], (items) => items.count || 0],
        results: [(s) => [s.items], (items) => items.results],
        selectedItem: [(s) => [s.index, s.items], (index, items) => (index >= 0 ? items.results[index] : undefined)],
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
