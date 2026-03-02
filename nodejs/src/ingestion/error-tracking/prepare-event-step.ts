import { DateTime } from 'luxon'

import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, ISOTimestamp, Person, PreIngestionEvent, Team } from '~/types'
import { uuidFromDistinctId } from '~/worker/ingestion/person-uuid'

import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface ErrorTrackingPrepareEventInput {
    event: PluginEvent
    team: Team
    person: Person | null
    headers: EventHeaders
}

/**
 * Output adds preparedEvent and resolved person, removes event/team (no longer needed).
 * Uses Omit to preserve any additional fields from input type T.
 */
export type ErrorTrackingPrepareEventOutput<T> = Omit<T, 'event' | 'team' | 'person'> & {
    preparedEvent: PreIngestionEvent
    person: Person // Always defined (placeholder if not found)
    processPerson: boolean
    historicalMigration: boolean
}

/**
 * Creates a step that prepares error tracking events for emission to ClickHouse.
 *
 * This step:
 * 1. Converts PluginEvent to PreIngestionEvent format
 * 2. Creates a placeholder person if none exists (propertyless mode)
 * 3. Extracts historical_migration flag from headers
 *
 * The output is compatible with createCreateEventStep() and createEmitEventStep().
 */
export function createErrorTrackingPrepareEventStep<T extends ErrorTrackingPrepareEventInput>(): ProcessingStep<
    T,
    ErrorTrackingPrepareEventOutput<T>
> {
    return function errorTrackingPrepareEventStep(input) {
        const { event, team, person, headers } = input

        // Convert PluginEvent to PreIngestionEvent
        const properties = { ...(event.properties ?? {}) }

        // Remove $set and $set_once from properties.
        //
        // Error tracking events ($exception) are in NO_PERSON_UPDATE_EVENTS, meaning
        // person updates are never written to the database. However, createEvent()
        // merges properties.$set into person_properties when processPerson=true.
        // This would cause person_properties to contain values that don't actually
        // exist on the person (e.g., GeoIP data from the Hog transformer).
        //
        // By removing $set/$set_once here, we ensure person_properties only contains
        // the actual person properties from the database, matching Cymbal's behavior.
        delete properties.$set
        delete properties.$set_once

        const preparedEvent: PreIngestionEvent = {
            eventUuid: event.uuid,
            event: event.event,
            teamId: team.id,
            projectId: team.project_id,
            distinctId: event.distinct_id,
            properties,
            timestamp: (event.timestamp ?? event.now) as ISOTimestamp,
        }

        // If we have a person from the read-only lookup, use it.
        // Otherwise, create a placeholder person with a deterministic UUID.
        //
        // NOTE: This pipeline does NOT create persons in the database (unlike the
        // analytics pipeline). We only do a read-only lookup. This diverges from
        // Cymbal's behavior, which omits person fields entirely when no person is
        // found. Here we include placeholder values to satisfy the type system and
        // downstream steps. The deterministic UUID ensures the same distinct_id
        // always maps to the same person_id for consistency.
        const resolvedPerson: Person = person ?? {
            team_id: team.id,
            uuid: uuidFromDistinctId(team.id, event.distinct_id),
            properties: {},
            created_at: DateTime.utc(1970, 1, 1, 0, 0, 5), // Marker timestamp for debugging
        }

        // Error tracking always uses processPerson=true to:
        // 1. Preserve $group_* properties (deleted in propertyless mode)
        // 2. Include person properties in events (when a real person is found)
        const processPerson = true

        const historicalMigration = headers.historical_migration ?? false

        // Use spread to preserve any additional fields from input (e.g., message)
        // Then add/override with our prepared fields
        const { event: _event, team: _team, person: _person, ...rest } = input
        return Promise.resolve(
            ok({
                ...rest,
                preparedEvent,
                person: resolvedPerson,
                processPerson,
                historicalMigration,
            })
        )
    }
}
