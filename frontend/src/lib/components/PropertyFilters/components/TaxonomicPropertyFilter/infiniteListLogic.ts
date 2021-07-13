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

const createEmptyListStorage = (searchQuery = ''): ListStorage => ({ results: [], searchQuery, count: 0 })

export const infiniteListLogic = kea<infiniteListLogicType<ListFuse, ListStorage, LoaderOptions>>({
    props: {} as TaxonomicPropertyFilterListLogicProps,

    key: (props) => `${props.pageKey}-${props.filterIndex}-${props.type}`,

    connect: (props: TaxonomicPropertyFilterListLogicProps) => ({
        values: [taxonomicPropertyFilterLogic(props), ['searchQuery']],
        actions: [taxonomicPropertyFilterLogic(props), ['setSearchQuery']],
    }),

    actions: {
        setLimit: (limit: number) => ({ limit }),
        onRowsRendered: (rowInfo: RenderedRows) => ({ rowInfo }),
        loadItems: (options: LoaderOptions) => options,
    },

    reducers: () => ({
        limit: [
            100,
            {
                setLimit: (_, { limit }) => limit,
            },
        ],
    }),

    loaders: ({ values }) => ({
        endpointItems: [
            createEmptyListStorage(),
            {
                loadItems: async ({ offset, limit }, breakpoint) => {
                    await breakpoint(150)

                    const { remoteEndpoint, searchQuery } = values

                    if (!remoteEndpoint) {
                        return createEmptyListStorage(searchQuery)
                    }
                    const response: EventDefinitionStorage = await api.get(
                        combineUrl(
                            remoteEndpoint,
                            {
                                search: searchQuery,
                                limit,
                                offset,
                            },
                            ''
                        ).url
                    )
                    breakpoint()

                    return {
                        results: appendAtIndex(
                            values.items.searchQuery === values.searchQuery ? values.items.results : [],
                            response.results,
                            offset
                        ),
                        searchQuery: values.searchQuery,
                        count: response.count,
                    }
                },
            },
        ],
    }),

    listeners: ({ values, actions }) => ({
        onRowsRendered: ({ rowInfo: { startIndex, overscanStopIndex } }) => {
            if (values.isRemoteDataSource) {
                let mustLoad = false
                for (let i = startIndex; i < overscanStopIndex; i++) {
                    if (!values.results[i]) {
                        mustLoad = true
                    }
                }
                if (mustLoad) {
                    actions.loadItems({ offset: startIndex, limit: values.limit })
                }
            }
        },
        setSearchQuery: () => {
            if (values.isRemoteDataSource) {
                console.log('setting search query')
                actions.loadItems({ offset: 0, limit: values.limit })
            }
        },
    }),

    selectors: {
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
            (s) => [s.isRemoteDataSource, s.endpointItems, s.localItems],
            (isRemoteDataSource, endpointItems, localItems) => (isRemoteDataSource ? endpointItems : localItems),
        ],
        totalCount: [(s) => [s.items], (items) => items.count || 0],
        results: [(s) => [s.items], (items) => items.results],
    },

    events: ({ actions, values }) => ({
        afterMount: () => {
            if (values.isRemoteDataSource) {
                actions.loadItems({ offset: 0, limit: values.limit })
            }
        },
    }),
})
