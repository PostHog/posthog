import { events, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { eventIngestionRestrictionLogicType } from './eventIngestionRestrictionLogicType'

export enum RestrictionType {
    DROP_EVENT_FROM_INGESTION = 'drop_event_from_ingestion',
    SKIP_PERSON_PROCESSING = 'skip_person_processing',
    FORCE_OVERFLOW_FROM_INGESTION = 'force_overflow_from_ingestion',
}

export interface EventIngestionRestriction {
    restriction_type: RestrictionType
    distinct_ids: string[] | null
}

export const eventIngestionRestrictionLogic = kea<eventIngestionRestrictionLogicType>([
    path(['lib', 'logic', 'eventIngestionRestrictionLogic']),

    loaders(() => ({
        eventIngestionRestrictions: {
            __default: [] as EventIngestionRestriction[],
            loadEventIngestionRestrictions: async () => {
                try {
                    const response = await api.get('api/environments/@current/event_ingestion_restrictions/')
                    return response
                } catch (error) {
                    console.error('Failed to load event ingestion restrictions:', error)
                    return []
                }
            },
        },
    })),

    selectors({
        hasAnyRestriction: [
            (s) => [s.eventIngestionRestrictions],
            (eventIngestionRestrictions): boolean => {
                return eventIngestionRestrictions.length > 0
            },
        ],
    }),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadEventIngestionRestrictions()
        },
    })),
])
