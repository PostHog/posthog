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
                const response = await api.eventDefinitions.list({
                    limit: 10,
                    ordering: '-created_at',
                })
                return response.results
            },
        },
    }),

    afterMount(({ actions }) => actions.loadNewEvents()),
])
