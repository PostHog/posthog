import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { v4 } from 'uuid'

import { EventHeaders, PipelineEvent, ProjectId, Team } from '../../types'
import { PipelineResultType, isDropResult } from '../pipelines/results'
import { DropOldEventsInput, createDropOldEventsStep } from './drop-old-events-step'

describe('createDropOldEventsStep', () => {
    const dropOldEventsStep = createDropOldEventsStep()

    it.each([
        { dropThreshold: null, eventAgeSeconds: 7200, description: 'threshold is null' },
        { dropThreshold: 0, eventAgeSeconds: 7200, description: 'threshold is 0' },
        { dropThreshold: 3600, eventAgeSeconds: 1800, description: 'event is younger than threshold' },
        { dropThreshold: 3600, eventAgeSeconds: 3600, description: 'event is exactly at threshold' },
        { dropThreshold: 3600, eventAgeSeconds: -3600, description: 'event is in the future' },
    ])('passes through event when $description', async ({ dropThreshold, eventAgeSeconds }) => {
        const input = createTestInput({ dropThreshold, eventAgeSeconds })

        const result = await dropOldEventsStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
    })

    it('drops event older than threshold with warning', async () => {
        const input = createTestInput({ dropThreshold: 3600, eventAgeSeconds: 7200 }) // threshold: 1h, age: 2h

        const result = await dropOldEventsStep(input)

        expect(result.type).toBe(PipelineResultType.DROP)
        expect(isDropResult(result) && result.reason).toBe('event_too_old')
        expect(result.warnings).toHaveLength(1)
        expect(result.warnings[0]).toMatchObject({
            type: 'event_dropped_too_old',
            details: {
                eventUuid: input.eventWithTeam.event.uuid,
                event: '$pageview',
                distinctId: 'user-1',
                dropThresholdSeconds: 3600,
            },
            alwaysSend: false,
        })
        expect(result.warnings[0].details.ageInSeconds).toBeGreaterThanOrEqual(7199)
    })

    it('passes through when timestamp header is missing', async () => {
        const input = createTestInput({
            dropThreshold: 3600,
            headers: { timestamp: undefined },
        })

        const result = await dropOldEventsStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
    })

    it('uses current time when now header is missing', async () => {
        const input = createTestInput({
            dropThreshold: 3600, // 1h threshold
            eventAgeSeconds: 7200, // 2h old
            headers: { now: undefined },
        })

        const result = await dropOldEventsStep(input)

        // Event should be dropped based on timestamp vs current time
        expect(result.type).toBe(PipelineResultType.DROP)
    })

    it('uses timestamp from headers (already normalized by Rust capture service)', async () => {
        const now = DateTime.utc()
        // Timestamp header is set to 2h ago by capture service (after clock skew correction)
        const normalizedTimestamp = now.minus({ hours: 2 })

        const input = createTestInput({
            dropThreshold: 3600, // 1h threshold
            event: {
                // Event body timestamp is irrelevant - we use header
                timestamp: now.minus({ minutes: 1 }).toISO()!,
            },
            headers: {
                // Capture service already normalized this with clock skew correction
                timestamp: normalizedTimestamp.toMillis().toString(),
                now: now.toJSDate(),
            },
        })

        const result = await dropOldEventsStep(input)

        // Event should be dropped based on header timestamp (2h old), not event body (1m old)
        expect(result.type).toBe(PipelineResultType.DROP)
    })

    describe('robustness to invalid data', () => {
        it.each([
            { headers: undefined, description: 'headers is undefined' },
            { headers: null, description: 'headers is null' },
        ])('passes through when $description', async ({ headers }) => {
            const input = createTestInput({
                dropThreshold: 3600,
                headers: headers as null | undefined,
            })

            const result = await dropOldEventsStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
        })

        it.each([
            { timestamp: 'not-a-number', description: 'timestamp is not a number' },
            { timestamp: '', description: 'timestamp is empty string' },
            { timestamp: 'NaN', description: 'timestamp parses to NaN' },
            { timestamp: 'Infinity', description: 'timestamp parses to Infinity' },
            { timestamp: '-Infinity', description: 'timestamp parses to -Infinity' },
        ])('passes through when $description', async ({ timestamp }) => {
            const input = createTestInput({
                dropThreshold: 3600,
                headers: { timestamp },
            })

            const result = await dropOldEventsStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
        })

        it.each([
            { now: new Date('invalid'), description: 'now is invalid Date' },
            { now: 'not-a-date' as unknown as Date, description: 'now is a string' },
            { now: 12345 as unknown as Date, description: 'now is a number' },
            { now: {} as unknown as Date, description: 'now is an object' },
        ])('uses current time when $description', async ({ now }) => {
            const currentTime = DateTime.utc()
            const eventTimestamp = currentTime.minus({ hours: 2 })

            const input = createTestInput({
                dropThreshold: 3600,
                headers: {
                    timestamp: eventTimestamp.toMillis().toString(),
                    now,
                },
            })

            const result = await dropOldEventsStep(input)

            // Should still drop because it falls back to current time
            expect(result.type).toBe(PipelineResultType.DROP)
        })
    })
})

function createTestInput(options: {
    dropThreshold?: number | null
    eventAgeSeconds?: number
    event?: Partial<PipelineEvent>
    team?: Partial<Team>
    headers?: Partial<EventHeaders> | null
}): DropOldEventsInput {
    const { dropThreshold = null, eventAgeSeconds = 0, event = {}, team = {} } = options

    const now = DateTime.utc()
    const eventTimestamp = now.minus({ seconds: eventAgeSeconds })

    // Only treat headers as null/undefined if explicitly passed as such
    const headersExplicitlyNull = 'headers' in options && (options.headers === null || options.headers === undefined)

    const resolvedHeaders = headersExplicitlyNull
        ? (options.headers as unknown as Pick<EventHeaders, 'timestamp' | 'now'>)
        : createTestHeaders({
              timestamp: eventTimestamp.toMillis().toString(),
              now: now.toJSDate(),
              ...options.headers,
          })

    return {
        eventWithTeam: {
            message: createTestMessage(),
            event: createTestEvent(event),
            team: createTestTeam({ drop_events_older_than_seconds: dropThreshold, ...team }),
            headers: createTestHeaders(),
        },
        headers: resolvedHeaders,
    }
}

function createTestTeam(overrides: Partial<Team> = {}): Team {
    return {
        id: 1,
        project_id: 1 as ProjectId,
        uuid: v4(),
        organization_id: v4(),
        name: 'Test Team',
        anonymize_ips: false,
        api_token: 'test-token',
        slack_incoming_webhook: null,
        session_recording_opt_in: false,
        person_processing_opt_out: null,
        heatmaps_opt_in: null,
        ingested_event: true,
        person_display_name_properties: null,
        test_account_filters: null,
        cookieless_server_hash_mode: null,
        timezone: 'UTC',
        available_features: [],
        drop_events_older_than_seconds: null,
        ...overrides,
    }
}

function createTestEvent(overrides: Partial<PipelineEvent> = {}): PipelineEvent {
    return {
        uuid: v4(),
        event: '$pageview',
        distinct_id: 'user-1',
        ip: null,
        site_url: 'https://test.posthog.com',
        now: DateTime.utc().toISO()!,
        properties: {},
        ...overrides,
    }
}

function createTestMessage(overrides: Partial<Message> = {}): Message {
    return {
        value: Buffer.from('{}'),
        size: 2,
        topic: 'test-topic',
        offset: 0,
        partition: 0,
        ...overrides,
    }
}

function createTestHeaders(overrides: Partial<EventHeaders> = {}): EventHeaders {
    const now = DateTime.utc()
    return {
        timestamp: now.toMillis().toString(),
        now: now.toJSDate(),
        force_disable_person_processing: false,
        historical_migration: false,
        ...overrides,
    }
}
