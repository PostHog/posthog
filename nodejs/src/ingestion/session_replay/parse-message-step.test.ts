import { Message } from 'node-rdkafka'
import { promisify } from 'node:util'
import { gzip } from 'zlib'

import { TopTracker } from '../../session-recording/top-tracker'
import { PipelineResultType } from '../pipelines/results'
import { ParseMessageStepInput, createParseMessageStep } from './parse-message-step'

const compressWithGzip = promisify(gzip)

describe('createParseMessageStep', () => {
    // Use a fixed time for tests that need predictable timestamp behavior
    const fixedTime = new Date('2023-01-01T00:00:00.000Z')
    const fixedTimeMs = fixedTime.getTime() // 1672531200000

    afterEach(() => {
        jest.useRealTimers()
    })

    function createSnapshotPayload(options: {
        sessionId: string
        windowId?: string
        snapshotItems: Array<{ type: number; timestamp: number }>
        snapshotSource?: string
        lib?: string
        distinctId?: string
    }): string {
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: options.sessionId,
                $window_id: options.windowId ?? 'window-1',
                $snapshot_items: options.snapshotItems,
                ...(options.snapshotSource !== undefined && { $snapshot_source: options.snapshotSource }),
                ...(options.lib !== undefined && { $lib: options.lib }),
            },
        }
        const rawMessage: Record<string, unknown> = {
            data: JSON.stringify(event),
        }
        if (options.distinctId !== undefined) {
            rawMessage.distinct_id = options.distinctId
        }
        return JSON.stringify(rawMessage)
    }

    function createValidSnapshotPayload(sessionId: string, windowId = 'window-1'): string {
        const now = Date.now()
        return createSnapshotPayload({
            sessionId,
            windowId,
            snapshotItems: [
                { type: 2, timestamp: now },
                { type: 3, timestamp: now + 1000 },
            ],
            distinctId: 'user-123',
        })
    }

    function createMessage(
        partition: number,
        offset: number,
        payload?: string,
        headers?: Record<string, string>,
        overrides?: Partial<Message>
    ): Message {
        const kafkaHeaders: Message['headers'] = headers
            ? Object.entries(headers).map(([key, value]) => ({ [key]: Buffer.from(value) }))
            : []

        const message: Message = {
            partition,
            offset,
            topic: 'test-topic',
            value: payload ? Buffer.from(payload) : null,
            key: Buffer.from('test-key'),
            timestamp: Date.now(),
            headers: kafkaHeaders,
            size: payload?.length ?? 0,
        }

        return { ...message, ...overrides }
    }

    function createInput(
        partition: number,
        offset: number,
        payload?: string,
        headers?: Record<string, string>,
        overrides?: Partial<Message>
    ): ParseMessageStepInput {
        return {
            message: createMessage(partition, offset, payload, headers, overrides),
        }
    }

    it('should parse valid messages and return ok results', async () => {
        const step = createParseMessageStep()
        const payload = createValidSnapshotPayload('session-1')
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage.session_id).toBe('session-1')
            expect(result.value.parsedMessage.distinct_id).toBe('user-123')
        }
    })

    it('should send messages with no value to DLQ', async () => {
        const step = createParseMessageStep()
        const input = createInput(0, 1, undefined)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe('message_value_or_timestamp_is_empty')
        }
    })

    it('should send messages with invalid JSON to DLQ', async () => {
        const step = createParseMessageStep()
        const input = createInput(0, 1, 'not valid json')

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe('invalid_json')
        }
    })

    it('should send messages with invalid message payload schema to DLQ', async () => {
        const step = createParseMessageStep()
        const input = createInput(0, 1, JSON.stringify({ invalid: 'schema' }))

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe('invalid_message_payload')
        }
    })

    it('should send non-snapshot messages to DLQ', async () => {
        const step = createParseMessageStep()
        const payload = JSON.stringify({
            distinct_id: 'user-123',
            data: JSON.stringify({ event: 'some_other_event', properties: {} }),
        })
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe('received_non_snapshot_message')
        }
    })

    it('should send messages with no valid rrweb events to DLQ', async () => {
        const step = createParseMessageStep()
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: 'session-1',
                $window_id: 'window-1',
                $snapshot_items: [], // Empty events array
            },
        }
        const payload = JSON.stringify({
            distinct_id: 'user-123',
            data: JSON.stringify(event),
        })
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe('message_contained_no_valid_rrweb_events')
        }
    })

    it('should handle gzipped messages', async () => {
        const step = createParseMessageStep()
        const payload = createValidSnapshotPayload('session-gzip')
        const gzippedPayload = await compressWithGzip(Buffer.from(payload))

        const message: Message = {
            partition: 0,
            offset: 1,
            topic: 'test-topic',
            value: gzippedPayload,
            key: Buffer.from('test-key'),
            timestamp: Date.now(),
            headers: [],
            size: gzippedPayload.length,
        }

        const result = await step({ message })

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage.session_id).toBe('session-gzip')
        }
    })

    it('should extract token from headers', async () => {
        const step = createParseMessageStep()
        const payload = createValidSnapshotPayload('session-1')
        const input = createInput(0, 1, payload, { token: 'my-team-token' })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage.token).toBe('my-team-token')
        }
    })

    it('should set token to null when not in headers', async () => {
        const step = createParseMessageStep()
        const payload = createValidSnapshotPayload('session-1')
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage.token).toBeNull()
        }
    })

    it('should populate metadata from message', async () => {
        const step = createParseMessageStep()
        const payload = createValidSnapshotPayload('session-1')
        const input = createInput(5, 42, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage.metadata.partition).toBe(5)
            expect(result.value.parsedMessage.metadata.offset).toBe(42)
            expect(result.value.parsedMessage.metadata.topic).toBe('test-topic')
        }
    })

    it('should calculate events range from snapshot items', async () => {
        const step = createParseMessageStep()
        const payload = createValidSnapshotPayload('session-1')
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage.eventsRange.start.isValid).toBe(true)
            expect(result.value.parsedMessage.eventsRange.end.isValid).toBe(true)
            expect(result.value.parsedMessage.eventsRange.end >= result.value.parsedMessage.eventsRange.start).toBe(
                true
            )
        }
    })

    it('should track parsing time when topTracker is provided', async () => {
        const topTracker = new TopTracker()
        const step = createParseMessageStep({ topTracker })
        const payload = createValidSnapshotPayload('session-1')
        const input = createInput(0, 1, payload, { token: 'test-token' })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)

        const trackingKey = 'token:test-token:session_id:session-1'
        const parseTime = topTracker.getCount('parse_time_ms_by_session_id', trackingKey)
        expect(parseTime).toBeGreaterThan(0)
    })

    it('should not track parsing time when topTracker is not provided', async () => {
        const step = createParseMessageStep()
        const payload = createValidSnapshotPayload('session-1')
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        // No error thrown when topTracker is not provided
    })

    it('should send messages with missing timestamp to DLQ', async () => {
        const step = createParseMessageStep()
        const payload = createValidSnapshotPayload('session-1')
        const input = createInput(0, 1, payload, undefined, { timestamp: undefined })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe('message_value_or_timestamp_is_empty')
        }
    })

    it('should send messages with invalid gzip data to DLQ', async () => {
        const step = createParseMessageStep()
        // Create a message with gzip magic bytes but invalid content
        const message: Message = {
            partition: 0,
            offset: 1,
            topic: 'test-topic',
            value: Buffer.from([0x1f, 0x8b, 0x08, 0x00, 0x00]),
            key: Buffer.from('test-key'),
            timestamp: Date.now(),
            headers: [],
            size: 5,
        }

        const result = await step({ message })

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe('invalid_gzip_data')
        }
    })

    it('should send messages with missing distinct_id to DLQ', async () => {
        const step = createParseMessageStep()
        const payload = createSnapshotPayload({
            sessionId: 'session-1',
            snapshotItems: [{ type: 2, timestamp: Date.now() }],
            // distinctId intentionally omitted
        })
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe('invalid_message_payload')
        }
    })

    it('should include snapshot_source and snapshot_library when present', async () => {
        const step = createParseMessageStep()
        const payload = createSnapshotPayload({
            sessionId: 'session-1',
            snapshotItems: [
                { type: 2, timestamp: Date.now() },
                { type: 3, timestamp: Date.now() + 1000 },
            ],
            snapshotSource: 'test-source',
            lib: 'test-lib',
            distinctId: 'user-123',
        })
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage.snapshot_source).toBe('test-source')
            expect(result.value.parsedMessage.snapshot_library).toBe('test-lib')
        }
    })

    it('should set snapshot_source and snapshot_library to null when not present', async () => {
        const step = createParseMessageStep()
        const payload = createSnapshotPayload({
            sessionId: 'session-1',
            snapshotItems: [
                { type: 2, timestamp: Date.now() },
                { type: 3, timestamp: Date.now() + 1000 },
            ],
            distinctId: 'user-123',
        })
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage.snapshot_source).toBeNull()
            expect(result.value.parsedMessage.snapshot_library).toBeNull()
        }
    })

    it('should filter out events with zero or negative timestamps', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(fixedTime)

        const step = createParseMessageStep()
        const payload = createSnapshotPayload({
            sessionId: 'session-1',
            snapshotItems: [
                { type: 1, timestamp: fixedTimeMs },
                { type: 2, timestamp: 0 },
                { type: 3, timestamp: -1000 },
                { type: 4, timestamp: fixedTimeMs + 1000 },
            ],
            distinctId: 'user-123',
        })
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            const events = result.value.parsedMessage.eventsByWindowId['window-1']
            expect(events).toHaveLength(2)
            expect(events).toEqual([
                { type: 1, timestamp: fixedTimeMs },
                { type: 4, timestamp: fixedTimeMs + 1000 },
            ])
        }
    })

    it('should use min/max for timestamp range instead of first/last', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(fixedTime)

        const step = createParseMessageStep()
        const payload = createSnapshotPayload({
            sessionId: 'session-1',
            snapshotItems: [
                { type: 1, timestamp: fixedTimeMs + 2000 }, // Not the smallest
                { type: 2, timestamp: fixedTimeMs }, // Smallest
                { type: 3, timestamp: fixedTimeMs + 4000 }, // Not the largest
                { type: 4, timestamp: fixedTimeMs + 5000 }, // Largest
                { type: 5, timestamp: fixedTimeMs + 3000 }, // Middle
            ],
            distinctId: 'user-123',
        })
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage.eventsRange.start.toMillis()).toBe(fixedTimeMs)
            expect(result.value.parsedMessage.eventsRange.end.toMillis()).toBe(fixedTimeMs + 5000)
        }
    })

    it('should drop messages with events too far in the future (>7 days)', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(fixedTime)

        const step = createParseMessageStep()
        const eightDaysInFuture = fixedTimeMs + 8 * 24 * 60 * 60 * 1000
        const payload = createSnapshotPayload({
            sessionId: 'session-1',
            snapshotItems: [
                { type: 1, timestamp: fixedTimeMs },
                { type: 2, timestamp: eightDaysInFuture },
            ],
            distinctId: 'user-123',
        })
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DROP)
        if (result.type === PipelineResultType.DROP) {
            expect(result.reason).toBe('message_timestamp_diff_too_large')
        }
    })

    it('should drop messages with events too far in the past (>7 days)', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(fixedTime)

        const step = createParseMessageStep()
        const eightDaysInPast = fixedTimeMs - 8 * 24 * 60 * 60 * 1000
        const payload = createSnapshotPayload({
            sessionId: 'session-1',
            snapshotItems: [
                { type: 1, timestamp: fixedTimeMs },
                { type: 2, timestamp: eightDaysInPast },
            ],
            distinctId: 'user-123',
        })
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DROP)
        if (result.type === PipelineResultType.DROP) {
            expect(result.reason).toBe('message_timestamp_diff_too_large')
        }
    })

    it('should accept messages with events within 7 days', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(fixedTime)

        const step = createParseMessageStep()
        const sixDaysInFuture = fixedTimeMs + 6 * 24 * 60 * 60 * 1000
        const sixDaysInPast = fixedTimeMs - 6 * 24 * 60 * 60 * 1000
        const payload = createSnapshotPayload({
            sessionId: 'session-1',
            snapshotItems: [
                { type: 1, timestamp: sixDaysInPast },
                { type: 2, timestamp: fixedTimeMs },
                { type: 3, timestamp: sixDaysInFuture },
            ],
            distinctId: 'user-123',
        })
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage.eventsByWindowId['window-1']).toHaveLength(3)
            expect(result.value.parsedMessage.eventsRange.start.toMillis()).toBe(sixDaysInPast)
            expect(result.value.parsedMessage.eventsRange.end.toMillis()).toBe(sixDaysInFuture)
        }
    })

    it('should include ingestion warning when dropping messages with timestamp diff too large', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(fixedTime)

        const step = createParseMessageStep()
        const eightDaysInFuture = fixedTimeMs + 8 * 24 * 60 * 60 * 1000
        const payload = createSnapshotPayload({
            sessionId: 'session-1',
            snapshotItems: [
                { type: 1, timestamp: fixedTimeMs },
                { type: 2, timestamp: eightDaysInFuture },
            ],
            distinctId: 'user-123',
        })
        const input = createInput(0, 1, payload)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DROP)
        expect(result.warnings).toHaveLength(1)
        expect(result.warnings[0]).toEqual({
            type: 'message_timestamp_diff_too_large',
            details: {
                startDiffDays: expect.any(Number),
                endDiffDays: expect.any(Number),
                thresholdDays: 7,
            },
        })
        // The end timestamp is 8 days in the future
        expect(result.warnings[0].details.endDiffDays).toBeGreaterThanOrEqual(8)
    })
})
