import { MakeLogicType, afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { EventDefinition } from '~/types'

export interface newEventsLogicValues {
    newEvents: EventDefinition[]
    newEventsLoading: boolean
}

export interface newEventsLogicActions {
    loadNewEvents: () => any
    loadNewEventsFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
    loadNewEventsSuccess: (
        newEvents: EventDefinition[],
        payload?: any
    ) => {
        newEvents: EventDefinition[]
        payload?: any
    }
}

export type newEventsLogicType = MakeLogicType<newEventsLogicValues, newEventsLogicActions>

export const newEventsLogic = kea<newEventsLogicType>([
    path(['scenes', 'saved-insights', 'newEventsLogic']),
    loaders({
        newEvents: {
            __default: [] as EventDefinition[],
            loadNewEvents: async () => {
                try {
                    const response = await api.eventDefinitions.list({ limit: 10, ordering: '-created_at' })
                    return response.results
                } catch {
                    return []
                }
            },
        },
    }),
    afterMount(({ actions }) => actions.loadNewEvents()),
])
