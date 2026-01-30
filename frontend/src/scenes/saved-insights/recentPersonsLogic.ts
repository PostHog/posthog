import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { PersonType } from '~/types'

import type { recentPersonsLogicType } from './recentPersonsLogicType'

export const recentPersonsLogic = kea<recentPersonsLogicType>([
    path(['scenes', 'saved-insights', 'recentPersonsLogic']),

    loaders({
        persons: {
            __default: [] as PersonType[],
            loadPersons: async () => {
                // Fetch persons, they will be sorted by last_seen_at by default on the backend
                const response = await api.persons.list({ limit: 10 })
                return response.results
            },
        },
    }),

    afterMount(({ actions }) => actions.loadPersons()),
])
