import { kea } from 'kea'
import api from 'lib/api'
import { buildUrl } from 'lib/utils'
import { RenderedRows } from 'react-virtualized/dist/es/List'
import { EventDefinitionStorage } from '~/models/eventDefinitionsModel'
import { infiniteListLogicType } from './infiniteListLogicType'

interface ListStorage extends EventDefinitionStorage {
    searchQuery?: string // Query used for the results currently in state
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
    props: {} as {
        key: string
        type: string
        endpoint: string
        searchQuery?: string
    },

    key: (props) => props.key,

    actions: {
        setLimit: (limit: number) => ({ limit }),
        onRowsRendered: (rowInfo: RenderedRows) => ({ rowInfo }),
        loadItems: (options: LoaderOptions) => options,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
    },

    loaders: ({ actions, props, values }) => ({
        items: [
            { results: [], next: null, count: 0 } as ListStorage,
            {
                loadItems: async ({ offset = 0, limit = values.limit, newSearchQuery }: LoaderOptions, breakpoint) => {
                    await breakpoint(150)
                    const shouldResetResults = typeof newSearchQuery === 'string'
                    if (shouldResetResults) {
                        actions.setSearchQuery(newSearchQuery as string)
                        const url = buildUrl(props.endpoint, {
                            search: newSearchQuery,
                            limit,
                            offset,
                        })
                        const response: EventDefinitionStorage = await api.get(url)
                        return {
                            results: response.results,
                            next: response.next,
                            count: response.count,
                        }
                    } else {
                        const url = buildUrl(props.endpoint, {
                            limit,
                            offset,
                        })
                        const response: EventDefinitionStorage = await api.get(url)
                        return {
                            results: appendAtIndex(values.results, response.results, offset),
                            next: response.next,
                            count: response.count,
                        }
                    }
                },
            },
        ],
    }),

    listeners: ({ values, actions }) => ({
        onRowsRendered: ({ rowInfo: { startIndex, overscanStopIndex } }) => {
            if (!values.results[startIndex] || !values.results[overscanStopIndex]) {
                // Render the next chunk
                actions.loadItems({ offset: startIndex, limit: values.limit })
            }
        },
    }),

    reducers: () => ({
        limit: [
            100,
            {
                setLimit: (_, { limit }) => limit,
            },
        ],
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
    }),

    selectors: () => ({
        nextUrl: [(s) => [s.items], (items) => items.next],
        totalCount: [(s) => [s.items], (items) => items.count],
        results: [(s) => [s.items], (items) => items.results],
    }),

    events: ({ actions }) => ({
        afterMount: () => actions.loadItems({}),
    }),
})
