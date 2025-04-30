import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
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
    actions({
        loadEventIngestionRestrictionConfig: true,
        loadEventIngestionRestrictionConfigSuccess: (_, { eventIngestionRestrictions }) => ({eventIngestionRestrictions})
    }),
    reducers({
        eventIngestionRestrictions: [
            [] as EventIngestionRestriction[],
            {
                loadEventIngestionRestrictionConfigSuccess: (_, { eventIngestionRestrictions }) =>
                    eventIngestionRestrictions,
            },
        ],
    }),
    selectors({
        hasAnyRestriction: [
            (s) => [s.eventIngestionRestrictions],
            (eventIngestionRestrictions): boolean => eventIngestionRestrictions.length > 0,
        ],
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadEventIngestionRestrictionConfig()
        },
    })),
    listeners(({ actions }) => ({
        loadEventIngestionRestrictionConfig: async () => {
            try {
                const eventIngestionRestrictions = await api.get(
                    `api/environments/@current/get_event_ingestion_restriction_config/`
                )
                actions.loadEventIngestionRestrictionConfigSuccess({ eventIngestionRestrictions })
            } catch (error) {
                console.error('Failed to load event ingestion restriction config:', error)
            }
        },
    })),
])
