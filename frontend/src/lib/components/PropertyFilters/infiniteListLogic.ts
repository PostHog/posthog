import { kea } from 'kea'
import api from 'lib/api'
import { buildUrl } from 'lib/utils'
import { EventDefinitionStorage } from '~/models/eventDefinitionsModel'

import { infiniteListLogicType } from './infiniteListLogicType'

export const infiniteListLogic = kea<infiniteListLogicType>({
    props: {} as {
        pageKey: string
        type: string
        endpoint: string
    },
    key: (props) => `${props.pageKey}-${props.type}`,

    actions: () => ({
        appendItems: (items: EventDefinitionStorage) => ({ items }),
        setItems: (items: EventDefinitionStorage) => ({ items }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setItemsLoading: (itemsLoading: boolean) => ({ itemsLoading }),
    }),

    loaders: ({ props, values, actions }) => ({
        items: [
            { results: [], next: null, count: 0 } as EventDefinitionStorage,
            {
                loadItems: async ({ search = '', offset = 0, limit = 100 }: { search?: string, offset?: number, limit?: number }) => {
                    if (offset < values.minimumNextOffset) {
                        // We already have the requested range in state.
                        return values.items
                    }
                    const searchQueryUnchanged = search === values.searchQuery
                    const url = values.nextUrl && searchQueryUnchanged ? values.nextUrl : buildUrl(props.endpoint, {
                        search,
                        limit,
                        offset: searchQueryUnchanged ? values.minimumNextOffset : 0
                    })
                    const response: EventDefinitionStorage = await api.get(url)

                    actions.setSearchQuery(search)
                    return {
                        results: [...values.items.results, ...response.results],
                        next: response.next,
                        count: response.count,
                    }
                }
            }
        ]
    }),

    listeners: ({ actions }) => ({
        loadItems: () => {
            actions.setItemsLoading(true)
        },
        loadItemsSuccess: () => {
            actions.setItemsLoading(false)
        },
        loadItemsFailure: () => {
            actions.setItemsLoading(false)
        },
    }),

    reducers: () => ({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
        itemsLoading: [
            false,
            {
                setItemsLoading: (_, { itemsLoading }) => itemsLoading,
            },
        ],
    }),

    selectors: () => ({
        nextUrl: [
            (s) => [s.items],
            (items) => items.next
        ],
        totalCount: [
            (s) => [s.items],
            (items) => items.count
        ],
        results: [
            (s) => [s.items],
            (items) => items.results
        ],
        minimumNextOffset: [
            (s) => [s.items],
            (items) => items.results.length
        ],
    })
})
