import { kea } from 'kea'
import api from 'lib/api'
import { buildUrl } from 'lib/utils'
import { RenderedRows } from 'react-virtualized/dist/es/List'
import { EventDefinitionStorage } from '~/models/eventDefinitionsModel'
import { infiniteListLogicType } from './infiniteListLogicType'

interface ListStorage extends EventDefinitionStorage {
    searchQuery?: string // Query used for the results currently in state
    nextOffset: number
}

export const infiniteListLogic = kea<infiniteListLogicType<ListStorage>>({
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
        loadItems: (options: Record<string, number>) => options,
    },

    loaders: ({ props, values }) => ({
        items: [
            { results: [], next: null, nextOffset: 0, count: 0 } as ListStorage,
            {
                loadItems: async ({ offset = 0, limit = values.limit }: { offset?: number; limit?: number }) => {
                    const shouldBuildUrl = !values.nextUrl || props.searchQuery !== values.items.searchQuery
                    const url = shouldBuildUrl
                        ? buildUrl(props.endpoint, {
                              search: props.searchQuery,
                              limit,
                              offset,
                          })
                        : values.nextUrl
                    const response: EventDefinitionStorage = await api.get(url)
                    return {
                        results: [...values.results, ...response.results],
                        next: response.next,
                        nextOffset: values.items.nextOffset += response.results.length,
                        count: response.count,
                    }
                },
            },
        ],
    }),

    listeners: ({ values, actions }) => ({
        onRowsRendered: ({ rowInfo: { startIndex, stopIndex } }) => {
            if (startIndex >= values.totalCount - values.limit && stopIndex >= values.totalCount) {
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
