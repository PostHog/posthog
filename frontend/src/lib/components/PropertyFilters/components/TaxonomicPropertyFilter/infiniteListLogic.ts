import { kea } from 'kea'
import { combineUrl } from 'kea-router'
import api from 'lib/api'
import { RenderedRows } from 'react-virtualized/dist/es/List'
import { EventDefinitionStorage } from '~/models/eventDefinitionsModel'
import { infiniteListLogicType } from './infiniteListLogicType'
import { TaxonomicPropertyFilterListLogicProps } from 'lib/components/PropertyFilters/types'
import { groups } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/groups'
import { taxonomicPropertyFilterLogic } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/taxonomicPropertyFilterLogic'
import { EventDefinition } from '~/types'
import Fuse from 'fuse.js'

interface ListStorage {
    results: EventDefinition[]
    searchQuery?: string // Query used for the results currently in state
    count: number
    queryChanged?: boolean
    first?: boolean
}

interface LoaderOptions {
    offset: number
    limit: number
}

type ListFuse = Fuse<EventDefinition> // local alias for typegen

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

export const infiniteListLogic = kea<infiniteListLogicType<ListFuse, ListStorage, LoaderOptions>>({
    props: {} as TaxonomicPropertyFilterListLogicProps,

    key: (props) => `${props.pageKey}-${props.filterIndex}-${props.type}`,

    connect: (props: TaxonomicPropertyFilterListLogicProps) => ({
        values: [taxonomicPropertyFilterLogic(props), ['searchQuery', 'filter']],
        actions: [taxonomicPropertyFilterLogic(props), ['setSearchQuery', 'selectItem as selectFilterItem']],
    }),

    actions: {
        selectSelected: (onComplete?: () => void) => ({ onComplete }),
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
    },

    loaders: ({ values }) => ({
        remoteItems: [
            createEmptyListStorage('', true),
            {
                loadRemoteItems: async ({ offset, limit }, breakpoint) => {
                    // avoid the 150ms delay on first load
                    if (!values.remoteItems.first) {
                        await breakpoint(150)
                    }

                    const { remoteEndpoint, searchQuery } = values

                    if (!remoteEndpoint) {
                        // should not have been here in the first place!
                        return createEmptyListStorage(searchQuery)
                    }

                    const url = combineUrl(remoteEndpoint, {
                        search: searchQuery,
                        limit,
                        offset,
                    }).url

                    let response: EventDefinitionStorage

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
                        results: appendAtIndex(queryChanged ? [] : values.items.results, response.results, offset),
                        searchQuery: values.searchQuery,
                        queryChanged,
                        count: response.count,
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
        selectSelected: ({ onComplete }) => {
            const item = values.selectedItem
            if (item) {
                actions.selectFilterItem(props.type, item.id, item.name)
                onComplete?.()
            }
        },
    }),

    selectors: {
        isLoading: [(s) => [s.remoteItemsLoading], (remoteItemsLoading) => remoteItemsLoading],
        group: [() => [(_, props) => props.type], (type) => groups.find((g) => g.type === type)],
        remoteEndpoint: [(s) => [s.group], (group) => group?.endpoint || null],
        isRemoteDataSource: [(s) => [s.remoteEndpoint], (remoteEndpoint) => !!remoteEndpoint],
        rawLocalItems: [
            () => [
                (state, props) => {
                    const group = groups.find((g) => g.type === props.type)
                    if (group?.logic && group?.value) {
                        return group.logic.selectors[group.value]?.(state) || null
                    }
                    return null
                },
            ],
            (rawLocalItems: EventDefinition[]) => rawLocalItems,
        ],
        fuse: [
            (s) => [s.rawLocalItems],
            (rawLocalItems): ListFuse =>
                new Fuse(rawLocalItems || [], {
                    keys: ['name'],
                    threshold: 0.3,
                }),
        ],
        localItems: [
            (s) => [s.rawLocalItems, s.group, s.searchQuery, s.fuse],
            (rawLocalItems, group, searchQuery, fuse): ListStorage => {
                if (rawLocalItems) {
                    const filteredItems = searchQuery
                        ? fuse.search(searchQuery).map((result) => (group?.map ? group.map(result.item) : result.item))
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
    },

    events: ({ actions, values, props }) => ({
        afterMount: () => {
            if (values.isRemoteDataSource) {
                actions.loadRemoteItems({ offset: 0, limit: values.limit })
            } else if (values.filter?.type === props.type) {
                const {
                    filter: { key, value },
                    results,
                } = values

                if (props.type === 'cohort') {
                    actions.setIndex(results.findIndex((r) => r.id === value))
                } else {
                    actions.setIndex(results.findIndex((r) => r.name === key))
                }
            }
        },
    }),
})
