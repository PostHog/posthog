import { DateTime } from 'luxon'
import { validate as isValidUuid, version as uuidVersion } from 'uuid'

import { parseDate } from '~/ingestion/common/timestamps'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PipelineEvent } from '~/types'

// Mirrors UUID_V7_TIMESTAMP_BUFFER in posthog/hogql/transforms/uuid_timestamp_bounds.py: uuid point
// lookups only search timestamps within this window of the uuid-embedded time.
export const UUID_V7_TIMESTAMP_DIVERGENCE_THRESHOLD_MS = 3 * 24 * 60 * 60 * 1000

const MS_PER_DAY = 24 * 60 * 60 * 1000

function uuidV7EmbeddedMs(uuid: unknown): number | null {
    if (typeof uuid !== 'string' || !isValidUuid(uuid) || uuidVersion(uuid) !== 7) {
        return null
    }
    // The high 48 bits (first 12 hex digits) hold the Unix millisecond timestamp.
    return parseInt(uuid.slice(0, 8) + uuid.slice(9, 13), 16)
}

/**
 * Warns when an event's UUIDv7 embeds a time more than three days from the event's timestamp.
 * The event is ingested unchanged, but bounded uuid point lookups won't find it.
 */
export function createValidateEventUuidTimestampStep<T extends { event: PipelineEvent }>(): ProcessingStep<T, T> {
    return function validateEventUuidTimestampStep(input) {
        const { event } = input

        const embeddedMs = uuidV7EmbeddedMs(event.uuid)
        if (embeddedMs === null) {
            return Promise.resolve(ok(input))
        }

        // A missing or empty timestamp ends up as ingestion time, which `now` approximates
        // (parseEventTimestamp treats '' as missing too).
        const timestamp = parseDate(event.timestamp || event.now)
        if (!timestamp.isValid) {
            return Promise.resolve(ok(input))
        }

        const divergenceMs = Math.abs(timestamp.toMillis() - embeddedMs)
        if (divergenceMs <= UUID_V7_TIMESTAMP_DIVERGENCE_THRESHOLD_MS) {
            return Promise.resolve(ok(input))
        }

        const rawLib = event.properties?.['$lib']
        const lib = typeof rawLib === 'string' ? rawLib : ''

        const warnings: PipelineWarning[] = [
            {
                type: 'event_uuid_timestamp_divergent',
                details: {
                    eventUuid: event.uuid,
                    event: event.event,
                    distinctId: event.distinct_id,
                    lib,
                    eventTimestamp: timestamp.toUTC().toISO(),
                    uuidTimestamp: DateTime.fromMillis(embeddedMs, { zone: 'utc' }).toISO(),
                    divergenceDays: Math.round(divergenceMs / MS_PER_DAY),
                },
                // Surface each sending library independently.
                key: lib,
            },
        ]

        return Promise.resolve(ok(input, [], warnings))
    }
}
