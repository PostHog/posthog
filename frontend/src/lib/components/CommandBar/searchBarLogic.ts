import { kea, path, actions, reducers, selectors, defaults } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { searchBarLogicType } from './searchBarLogicType'
import { ResultTypeWithAll, SearchResponse } from './types'

export const searchBarLogic = kea<searchBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'searchBarLogic']),
    actions(() => ({
        setSearchQuery: (query: string) => ({ query }),
        onArrowUp: true,
        onArrowDown: true,
        onMouseEnterResult: (index: number) => ({ index }),
        onMouseLeaveResult: true,
    })),
    loaders({
        searchResponse: [
            null as SearchResponse | null,
            {
                setSearchQuery: async ({ query }) => {
                    const result = await api.get(`api/projects/@current/search?q=${query}`)
                    return result
                },
            },
        ],
    }),
    reducers(({ values }) => ({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        keyboardResultIndex: [
            0,
            {
                // setInput: () => 0,
                // executeResult: () => 0,
                // activateFlow: () => 0,
                // backFlow: () => 0,
                onArrowUp: (previousIndex) => (previousIndex > 0 ? previousIndex - 1 : 0),
                onArrowDown: (previousIndex) =>
                    values.maxIndex !== null && previousIndex < values.maxIndex ? previousIndex + 1 : 0,
            },
        ],
        hoverResultIndex: [
            null as number | null,
            {
                // activateFlow: () => null,
                // backFlow: () => null,
                onMouseEnterResult: (_, { index }) => index,
                onMouseLeaveResult: () => null,
                onArrowUp: () => null,
                onArrowDown: () => null,
            },
        ],
        activeTab: ['all' as ResultTypeWithAll, {}],
    })),
    selectors(() => ({
        searchResults: [(s) => [s.searchResponse], (searchResponse) => searchResponse?.results],
        searchCounts: [(s) => [s.searchResponse], (searchResponse) => searchResponse?.counts],
        maxIndex: [(s) => [s.searchResults], (searchResults) => (searchResults ? searchResults.length : null)],
        activeResultIndex: [
            (s) => [s.keyboardResultIndex, s.hoverResultIndex],
            (keyboardResultIndex: number, hoverResultIndex: number | null) => {
                return hoverResultIndex ?? keyboardResultIndex
            },
        ],
    })),
])
