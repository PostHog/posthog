import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, ISOTimestamp, Person, PreIngestionEvent, Team } from '~/types'
import { invalidTimestampCounter } from '~/worker/ingestion/event-pipeline/metrics'
import { parseEventTimestamp } from '~/worker/ingestion/timestamps'

import { PipelineWarning } from '../pipelines/pipeline.interface'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface ErrorTrackingPrepareEventInput {
    event: PluginEvent
    team: Team
    person: Person | null
    headers: EventHeaders
}

/**
 * Output adds preparedEvent, removes event (no longer needed).
 * Person is optional - undefined if no person was found in the database.
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
 * 2. Validates timestamp (falls back to now if invalid)
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

        const warnings: PipelineWarning[] = []
        const invalidTimestampCallback = function (type: string, details: Record<string, any>) {
            invalidTimestampCounter.labels(type).inc()
            warnings.push({ type, details })
        }

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

        const timestamp = parseEventTimestamp(event, invalidTimestampCallback)

        const preparedEvent: PreIngestionEvent = {
            eventUuid: event.uuid,
            event: event.event,
            teamId: team.id,
            projectId: team.project_id,
            distinctId: event.distinct_id,
            properties,
            timestamp: timestamp.toISO() as ISOTimestamp,
        }

        // Error tracking always uses processPerson=true to:
        // 1. Preserve $group_* properties (deleted in propertyless mode)
        // 2. Include person properties in events (when a real person is found)
        const processPerson = true

        const historicalMigration = headers.historical_migration ?? false

        return Promise.resolve(
            ok(
                {
                    ...input,
                    preparedEvent,
                    person: person ?? undefined,
                    processPerson,
                    historicalMigration,
                },
                [],
                warnings
            )
        )
    }
}
