import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, ISOTimestamp, Person, PreIngestionEvent, Team } from '~/types'

import { stripBloatProperties } from '../event-processing/strip-bloat-properties'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface ErrorTrackingPrepareEventInput {
    event: PluginEvent
    team: Team
    person: Person | null
    headers: EventHeaders
}

/**
 * Output adds preparedEvent, removes event and person (transformed/consumed).
 * Preserves team and headers for downstream steps.
 */
export type ErrorTrackingPrepareEventOutput<T> = Omit<T, 'event' | 'person'> & {
    preparedEvent: PreIngestionEvent
    person?: Person
    processPerson: boolean
    historicalMigration: boolean
}

/**
 * Creates a step that prepares error tracking events for emission to ClickHouse.
 *
 * This step:
 * 1. Converts PluginEvent to PreIngestionEvent format
 * 2. Uses pre-validated timestamp (validated by cymbal processing step)
 * 3. Extracts historical_migration flag from headers
 *
 * The output is compatible with createCreateEventStep() and createEmitEventStep().
 */
export function createErrorTrackingPrepareEventStep<T extends ErrorTrackingPrepareEventInput>(): ProcessingStep<
    T,
    ErrorTrackingPrepareEventOutput<T>
> {
    return function errorTrackingPrepareEventStep(input) {
        const { event, person, ...rest } = input

        // Convert PluginEvent to PreIngestionEvent.
        // Remove $set and $set_once from properties because error tracking events
        // ($exception) are in NO_PERSON_UPDATE_EVENTS - person updates are never
        // written to the database. However, createEvent() merges properties.$set
        // into person_properties when processPerson=true, which would cause
        // person_properties to contain values that don't exist on the person
        // (e.g., GeoIP data from the Hog transformer). Mutation is safe since
        // the event is discarded after this step.
        const properties = event.properties ?? {}
        delete properties.$set
        delete properties.$set_once

        if (properties['$ip'] && input.team.anonymize_ips) {
            delete properties['$ip']
        }

        stripBloatProperties(properties)

        // Timestamp is already validated by the cymbal processing step
        const timestamp = event.timestamp as ISOTimestamp

        const preparedEvent: PreIngestionEvent = {
            eventUuid: event.uuid,
            event: event.event,
            teamId: rest.team.id,
            projectId: rest.team.project_id,
            distinctId: event.distinct_id,
            properties,
            timestamp,
        }

        // Error tracking always uses processPerson=true to:
        // 1. Preserve $group_* properties (deleted in propertyless mode)
        // 2. Include person properties in events (when a real person is found)
        const processPerson = true

        const historicalMigration = rest.headers.historical_migration ?? false

        return Promise.resolve(
            ok({
                ...rest,
                preparedEvent,
                person: person ?? undefined,
                processPerson,
                historicalMigration,
            })
        )
    }
}
