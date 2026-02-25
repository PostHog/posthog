import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { EventDefinition } from '~/types'

import type { newEventsLogicType } from './newEventsLogicType'

export const newEventsLogic = kea<newEventsLogicType>([
    path(['scenes', 'saved-insights', 'newEventsLogic']),

    loaders({
        newEvents: {
            __default: [] as EventDefinition[],
            loadNewEvents: async () => {
                try {
                    const response = await api.eventDefinitions.list({ limit: 10 })
                    return response.results.sort(
                        (a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime()
                    )
                } catch (error) {
                    console.error('Failed to load new events:', error)
                    return []
                }
            },
        },
    }),

    afterMount(({ actions }) => actions.loadNewEvents()),
])
