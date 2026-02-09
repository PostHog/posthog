import { DateTime } from 'luxon'

import { EventHeaders, IncomingEventWithTeam } from '../../types'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { PipelineResult, drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface DropOldEventsInput {
    eventWithTeam: IncomingEventWithTeam
    headers: Pick<EventHeaders, 'timestamp' | 'now'>
}

/**
 * Creates a pipeline step that drops events older than a team's configured threshold.
 *
 * If an event is too old, it returns a `drop` result with an ingestion warning
 * that will be sent to Kafka by `handleIngestionWarnings`.
 *
 * Uses the `timestamp` and `now` headers set by the Rust capture service.
 * The timestamp header contains milliseconds since epoch (already normalized with clock skew correction).
 * The now header contains the time when the event was received by the capture service.
 */
export function createDropOldEventsStep<T extends DropOldEventsInput>(): ProcessingStep<T, T> {
    return function dropOldEventsStep(input: T): Promise<PipelineResult<T>> {
        const { eventWithTeam, headers } = input
        const { event, team } = eventWithTeam

        // If no drop threshold is set (null) or set to 0, don't drop any events
        // Zero threshold is ignored to protect from misconfiguration bugs
        if (!team.drop_events_older_than_seconds) {
            return Promise.resolve(ok(input))
        }

        const eventTimestamp = parseEventTimestampFromHeaders(headers)
        if (!eventTimestamp) {
            return Promise.resolve(ok(input))
        }

        const now = parseNowFromHeaders(headers)
        const ageInSeconds = calculateAgeInSeconds(eventTimestamp, now)

        if (ageInSeconds > team.drop_events_older_than_seconds) {
            const warning: PipelineWarning = {
                type: 'event_dropped_too_old',
                details: {
                    eventUuid: event.uuid,
                    event: event.event,
                    distinctId: event.distinct_id,
                    eventTimestamp: eventTimestamp.toISO(),
                    ageInSeconds: Math.floor(ageInSeconds),
                    dropThresholdSeconds: team.drop_events_older_than_seconds,
                },
                alwaysSend: false,
            }
            return Promise.resolve(drop('event_too_old', [], [warning]))
        }

        return Promise.resolve(ok(input))
    }
}

function parseEventTimestampFromHeaders(headers: Pick<EventHeaders, 'timestamp'> | undefined): DateTime | undefined {
    if (!headers?.timestamp) {
        return undefined
    }

    const timestampMs = parseInt(headers.timestamp, 10)
    if (!Number.isFinite(timestampMs)) {
        return undefined
    }

    const eventTimestamp = DateTime.fromMillis(timestampMs)
    return eventTimestamp.isValid ? eventTimestamp : undefined
}

function parseNowFromHeaders(headers: Pick<EventHeaders, 'now'> | undefined): DateTime {
    if (headers?.now instanceof Date && !isNaN(headers.now.getTime())) {
        const now = DateTime.fromJSDate(headers.now)
        if (now.isValid) {
            return now
        }
    }
    return DateTime.utc()
}

function calculateAgeInSeconds(eventTimestamp: DateTime, now: DateTime): number {
    return now.diff(eventTimestamp, 'seconds').seconds
}
