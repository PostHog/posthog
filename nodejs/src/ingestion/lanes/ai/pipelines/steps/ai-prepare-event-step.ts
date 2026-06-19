import { invalidTimestampCounter } from '~/ingestion/common/event-pipeline/metrics'
import { parseEventTimestamp } from '~/ingestion/common/timestamps'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { stripBloatProperties } from '~/ingestion/steps/event-processing/strip-bloat-properties'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, ISOTimestamp, Person, PreIngestionEvent, Team } from '~/types'
import { sanitizeEventName } from '~/utils/db/utils'

export interface AiPrepareEventStepInput {
    normalizedEvent: PluginEvent
    team: Team
    person: Person | null
    processPerson: boolean
    headers: EventHeaders
}

/**
 * Output adds preparedEvent and coerces the fetched person to the shape
 * createCreateEventStep expects (`Person | undefined`). `normalizedEvent` is
 * consumed; everything else (team, headers, message, processPerson) is preserved.
 */
export type AiPrepareEventStepResult<T> = Omit<T, 'normalizedEvent' | 'person'> & {
    preparedEvent: PreIngestionEvent
    person?: Person
    historicalMigration: boolean
}

/**
 * Prepares AI events for emission. Mirrors the analytics prepare step
 * (parses/validates the timestamp from the normalized event), but is built for
 * the read-only person path like error tracking: it carries the batch-fetched
 * person through and strips `$set` / `$set_once`. Because the AI pipeline never
 * writes persons, those property mutations would otherwise leak into
 * person_properties on the emitted event (createEvent merges them when
 * processPerson=true) — values that were never persisted on the person.
 */
export function createAiPrepareEventStep<T extends AiPrepareEventStepInput>(): ProcessingStep<
    T,
    AiPrepareEventStepResult<T>
> {
    return function aiPrepareEventStep(input) {
        const { normalizedEvent, person, ...rest } = input

        const warnings: PipelineWarning[] = []
        const invalidTimestampCallback = function (type: string, details: Record<string, any>) {
            invalidTimestampCounter.labels(type).inc()
            warnings.push({ type, details })
        }

        const properties = normalizedEvent.properties!

        // Read-only mode: the person is never updated, so person-update props must
        // not leak into person_properties on the emitted event. Mutation is safe —
        // the event is consumed by this step.
        delete properties.$set
        delete properties.$set_once

        if (properties['$ip'] && input.team.anonymize_ips) {
            delete properties['$ip']
        }

        stripBloatProperties(properties)

        const timestamp = parseEventTimestamp(normalizedEvent, invalidTimestampCallback)

        const preparedEvent: PreIngestionEvent = {
            eventUuid: normalizedEvent.uuid,
            event: sanitizeEventName(normalizedEvent['event']),
            distinctId: String(normalizedEvent.distinct_id),
            properties,
            timestamp: timestamp.toISO() as ISOTimestamp,
            teamId: input.team.id,
            projectId: input.team.project_id,
        }

        const historicalMigration = input.headers.historical_migration ?? false

        return Promise.resolve(
            ok(
                {
                    ...rest,
                    preparedEvent,
                    person: person ?? undefined,
                    historicalMigration,
                },
                [],
                warnings
            )
        )
    }
}
