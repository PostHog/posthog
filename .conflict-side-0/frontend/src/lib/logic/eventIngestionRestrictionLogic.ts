import { kea, path, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'

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

    lazyLoaders(() => ({
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
        hasProjectNoticeRestriction: [
            (s) => [s.eventIngestionRestrictions],
            (eventIngestionRestrictions: EventIngestionRestriction[]): boolean => {
                return eventIngestionRestrictions.some(
                    (r: EventIngestionRestriction) =>
                        r.restriction_type === RestrictionType.DROP_EVENT_FROM_INGESTION ||
                        r.restriction_type === RestrictionType.SKIP_PERSON_PROCESSING
                )
            },
        ],
    }),
])
