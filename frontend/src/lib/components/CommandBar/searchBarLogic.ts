import { kea, path, actions, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { searchBarLogicType } from './searchBarLogicType'
import { ResultTypesWithAll, SearchResponse } from './types'

export const searchBarLogic = kea<searchBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'searchBarLogic']),
    actions({
        setSearchQuery: (query: string) => ({ query }),
        onMouseEnterResult: (index: number) => ({ index }),
        onMouseLeaveResult: true,
    }),
    reducers({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        keyboardResultIndex: [
            0,
            {
                // setInput: () => 0,
                // executeResult: () => 0,
                // activateFlow: () => 0,
                // backFlow: () => 0,
                // onArrowUp: (previousIndex) => (previousIndex > 0 ? previousIndex - 1 : 0),
                // onArrowDown: (previousIndex, { maxIndex }) => (previousIndex < maxIndex ? previousIndex + 1 : maxIndex),
            },
        ],
        hoverResultIndex: [
            null as number | null,
            {
                // activateFlow: () => null,
                // backFlow: () => null,
                onMouseEnterResult: (_, { index }) => index,
                onMouseLeaveResult: () => null,
                // onArrowUp: () => null,
                // onArrowDown: () => null,
            },
        ],
        activeTab: ['all' as ResultTypesWithAll, {}],
    }),
    selectors({
        activeResultIndex: [
            (s) => [s.keyboardResultIndex, s.hoverResultIndex],
            (keyboardResultIndex: number, hoverResultIndex: number | null) => {
                return hoverResultIndex ?? keyboardResultIndex
            },
        ],
    }),
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
])
