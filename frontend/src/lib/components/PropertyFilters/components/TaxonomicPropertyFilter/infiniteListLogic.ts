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
    offset?: number
    limit?: number
    newSearchQuery?: string
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
        values: [taxonomicPropertyFilterLogic(props as any), ['searchQuery']], // TODO: fix
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
        items: [
            { results: [], searchQuery: '', count: 0 } as ListStorage,
            {
                loadItems: async ({ offset = 0, limit = values.limit }, breakpoint) => {
                    await breakpoint(150)

                    if (!values.remoteEndpoint) {
                        return { results: [], seachQuery: values.searchQuery, count: 0 }
                    }
                    const response: EventDefinitionStorage = await api.get(
                        combineUrl(
                            values.remoteEndpoint,
                            {
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
            if ((values.isRemoteDataSource && !values.results[startIndex]) || !values.results[overscanStopIndex]) {
                // Render the next chunk
                actions.loadItems({ offset: startIndex, limit: values.limit })
            }
        },
    }),

    selectors: {
        group: [() => [(_, props) => props.type], (type) => groups.find((g) => g.type === type)],
        remoteEndpoint: [(s) => [s.group], ({ endpoint }) => endpoint],
        isRemoteDataSource: [(s) => [s.remoteEndpoint], (remoteEndpoint) => !!remoteEndpoint],
        totalCount: [(s) => [s.items], (items) => items.count],
        results: [(s) => [s.items], (items) => items.results],
    },

    events: ({ actions }) => ({
        afterMount: () => actions.loadItems({}),
    }),
})
