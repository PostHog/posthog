import { kea, path, actions, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { searchBarLogicType } from './searchBarLogicType'

export const searchBarLogic = kea<searchBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'searchBarLogic']),
    actions({
        setSearchQuery: (query: string) => ({ query }),
    }),
    reducers({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
    }),
    loaders({
        searchResults: [
            [],
            {
                setSearchQuery: async ({ query }) => {
                    const result = await api.get(`api/projects/@current/search?query)${query}`)
                    return result
                },
            },
        ],
    }),
])
