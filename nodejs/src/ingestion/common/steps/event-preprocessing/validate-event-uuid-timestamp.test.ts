import { DateTime } from 'luxon'

import { UUID7 } from '~/common/utils/utils'
import { PipelineResultType, ok } from '~/ingestion/framework/results'
import { createTestPipelineEvent } from '~/tests/helpers/pipeline-event'

import {
    UUID_V7_TIMESTAMP_DIVERGENCE_THRESHOLD_MS,
    createValidateEventUuidTimestampStep,
} from './validate-event-uuid-timestamp'

const EVENT_TIMESTAMP = '2025-06-15T12:00:00.000Z'
const EVENT_TIMESTAMP_MS = DateTime.fromISO(EVENT_TIMESTAMP).toMillis()

const uuidEmbedding = (ms: number): string => new UUID7(ms).toString()

describe('createValidateEventUuidTimestampStep', () => {
    const step = createValidateEventUuidTimestampStep()

    const createInput = (uuid: string | undefined, timestamp: string | undefined = EVENT_TIMESTAMP) => ({
        event: createTestPipelineEvent({
            uuid,
            event: 'custom_event',
            distinct_id: 'user123',
            team_id: 1,
            timestamp,
            properties: { $lib: 'posthog-python' },
        }),
    })

    it.each([
        ['uuid matching the timestamp exactly', uuidEmbedding(EVENT_TIMESTAMP_MS)],
        [
            'uuid diverging by exactly the threshold',
            uuidEmbedding(EVENT_TIMESTAMP_MS + UUID_V7_TIMESTAMP_DIVERGENCE_THRESHOLD_MS),
        ],
        ['v4 uuid', 'f47ac10b-58cc-4372-a567-0e02b2c3d479'],
        ['malformed uuid', 'not-a-uuid'],
    ])('does not warn for %s', async (_name, uuid) => {
        const input = createInput(uuid)
        expect(await step(input)).toEqual(ok(input))
    })

    it.each([
        ['ahead of', EVENT_TIMESTAMP_MS + UUID_V7_TIMESTAMP_DIVERGENCE_THRESHOLD_MS + 1000],
        ['behind', EVENT_TIMESTAMP_MS - 10 * 24 * 60 * 60 * 1000],
    ])('warns when the uuid-embedded time is %s the timestamp beyond the threshold', async (_name, embeddedMs) => {
        const uuid = uuidEmbedding(embeddedMs)
        const input = createInput(uuid)
        const result = await step(input)
        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toBe(input)
            expect(result.warnings).toHaveLength(1)
            expect(result.warnings[0]).toEqual({
                type: 'event_uuid_timestamp_divergent',
                details: {
                    eventUuid: uuid,
                    event: 'custom_event',
                    distinctId: 'user123',
                    lib: 'posthog-python',
                    eventTimestamp: EVENT_TIMESTAMP,
                    uuidTimestamp: DateTime.fromMillis(embeddedMs, { zone: 'utc' }).toISO(),
                    divergenceDays: expect.any(Number),
                },
                key: 'posthog-python',
            })
        }
    })

    it.each([
        ['missing', {}],
        ['empty', { timestamp: '' }],
    ])('compares against `now` when the timestamp is %s', async (_name, timestampOverride) => {
        // The helper's `now` (2021-01-01) is years from the uuid's embedded time.
        const input = {
            event: createTestPipelineEvent({ uuid: uuidEmbedding(EVENT_TIMESTAMP_MS), ...timestampOverride }),
        }
        const result = await step(input)
        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.warnings).toHaveLength(1)
        }
    })
})
