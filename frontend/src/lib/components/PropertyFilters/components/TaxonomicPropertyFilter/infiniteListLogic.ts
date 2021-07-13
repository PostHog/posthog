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

interface ListStorage {
    results: EventDefinition[]
    searchQuery?: string // Query used for the results currently in state
    count: number
}

interface LoaderOptions {
    offset: number
    limit: number
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

export const infiniteListLogic = kea<infiniteListLogicType<ListStorage, LoaderOptions>>({
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
            { results: [], searchQuery: '', count: 0 } as ListStorage,
            {
                loadItems: async ({ offset, limit }, breakpoint) => {
                    await breakpoint(150)

                    const { remoteEndpoint, searchQuery } = values

                    if (!remoteEndpoint) {
                        return { results: [], searchQuery, count: 0 }
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
        items: [
            (s) => [
                s.isRemoteDataSource,
                s.endpointItems,
                (state, { type }) => {
                    const group = groups.find((g) => g.type === type)
                    if (group?.logic && group?.value) {
                        return group.logic.selectors[group.value]?.(state) || null
                    }
                    return null
                },
            ],
            (isRemoteDataSource, endpointItems, localItems) => (isRemoteDataSource ? endpointItems : localItems),
        ],
        totalCount: [(s) => [s.items], (items) => items.count],
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
