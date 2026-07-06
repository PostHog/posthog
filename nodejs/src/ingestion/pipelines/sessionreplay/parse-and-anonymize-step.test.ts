import { Message } from 'node-rdkafka'
import { promisify } from 'node:util'
import { gzip } from 'zlib'

import { PipelineResultType } from '~/ingestion/framework/results'

import { createParseAndAnonymizeMessageStep } from './parse-and-anonymize-step'
import { SessionReplayHeaders } from './validate-headers-step'

const compressWithGzip = promisify(gzip)

// The native addon is the mocked boundary: these tests pin the TS side of the fused step — failure
// classification (dlq vs drop), the timestamp window, header/body agreement, and the ParsedMessageData
// assembly — not the scrub itself (that's covered by the Rust suite + shared fixtures).
const mockAnonymizeKafkaPayload = jest.fn()
jest.mock('@posthog/replay-anonymizer', () => ({
    anonymizeKafkaPayload: (payload: Buffer, contentEncoding?: string | null) =>
        mockAnonymizeKafkaPayload(payload, contentEncoding),
}))

describe('createParseAndAnonymizeMessageStep', () => {
    const step = createParseAndAnonymizeMessageStep()
    const now = Date.now()

    const headers: SessionReplayHeaders = {
        token: 'token-1',
        distinct_id: 'user-1',
        session_id: 'session-1',
    } as SessionReplayHeaders

    function kafkaMessage(value: Buffer | null = Buffer.from('{}')): Message {
        return {
            value,
            timestamp: now,
            partition: 3,
            topic: 'snapshots',
            offset: 42,
            size: value?.length ?? 0,
        } as Message
    }

    function addonSuccess(metaOverrides: Record<string, unknown> = {}): void {
        mockAnonymizeKafkaPayload.mockResolvedValue({
            failed: false,
            reason: null,
            error: null,
            lines: Buffer.from('["window-1",{"type":3,"timestamp":' + now + '}]\n'),
            meta: JSON.stringify({
                distinctId: 'user-1',
                sessionId: 'session-1',
                windowId: 'window-1',
                snapshotSource: 'web',
                snapshotLibrary: 'posthog-js',
                startTs: now,
                endTs: now + 1000,
                consoleLogCount: 1,
                consoleWarnCount: 2,
                consoleErrorCount: 3,
                events: [{ ts: now, flags: 5 }],
                ...metaOverrides,
            }),
        })
    }

    beforeEach(() => {
        mockAnonymizeKafkaPayload.mockReset()
    })

    it('assembles a pre-serialized ParsedMessageData from the addon output', async () => {
        addonSuccess()
        const result = await step({ message: kafkaMessage(), headers })

        expect(result.type).toBe(PipelineResultType.OK)
        const parsed = (result as any).value.parsedMessage
        expect(parsed.session_id).toBe('session-1')
        expect(parsed.distinct_id).toBe('user-1')
        expect(parsed.token).toBe('token-1')
        expect(parsed.eventsByWindowId).toEqual({})
        expect(parsed.preSerialized.lines.toString()).toContain('"window-1"')
        expect(parsed.preSerialized.events).toEqual([{ ts: now, flags: 5 }])
        expect(parsed.preSerialized.consoleWarnCount).toBe(2)
        expect(parsed.eventsRange.start.toMillis()).toBe(now)
        expect(parsed.eventsRange.end.toMillis()).toBe(now + 1000)
        expect(parsed.snapshot_source).toBe('web')
        expect(parsed.snapshot_library).toBe('posthog-js')
        expect(parsed.metadata).toEqual({ partition: 3, topic: 'snapshots', rawSize: 2, offset: 42, timestamp: now })
    })

    it('normalizes a UUID session id before comparing against the header', async () => {
        const upper = '019539D9-6B23-7E26-B0E3-3C8D3E2AD068'
        addonSuccess({ sessionId: upper })
        const result = await step({
            message: kafkaMessage(),
            headers: { ...headers, session_id: upper.toLowerCase() },
        })
        expect(result.type).toBe(PipelineResultType.OK)
        expect((result as any).value.parsedMessage.session_id).toBe(upper.toLowerCase())
    })

    it('hands the addon the raw bytes and content encoding (decompression lives in Rust)', async () => {
        addonSuccess()
        const raw = Buffer.from(JSON.stringify({ distinct_id: 'user-1', data: '{}' }))
        const zipped = await compressWithGzip(raw)
        await step({ message: kafkaMessage(zipped), headers })
        expect(mockAnonymizeKafkaPayload).toHaveBeenCalledWith(zipped, null)

        mockAnonymizeKafkaPayload.mockClear()
        addonSuccess()
        const lz4Message = kafkaMessage(raw)
        lz4Message.headers = [{ 'content-encoding': Buffer.from('lz4') }]
        await step({ message: lz4Message, headers })
        expect(mockAnonymizeKafkaPayload).toHaveBeenCalledWith(raw, 'lz4')
    })

    test.each([
        ['invalid_compressed_data', PipelineResultType.DLQ],
        ['invalid_json', PipelineResultType.DLQ],
        ['invalid_message_payload', PipelineResultType.DLQ],
        ['received_non_snapshot_message', PipelineResultType.DLQ],
        ['message_contained_no_valid_rrweb_events', PipelineResultType.DROP],
        ['anonymize_failed', PipelineResultType.DROP],
    ])('maps the addon failure reason %s to %s', async (reason, expectedType) => {
        mockAnonymizeKafkaPayload.mockResolvedValue({
            failed: true,
            reason,
            error: 'detail',
            lines: null,
            meta: null,
        })
        const result = await step({ message: kafkaMessage(), headers })
        expect(result.type).toBe(expectedType)
        expect((result as any).reason).toBe(reason)
    })

    it('fails closed when the addon promise rejects', async () => {
        mockAnonymizeKafkaPayload.mockRejectedValue(new Error('native panic'))
        const result = await step({ message: kafkaMessage(), headers })
        expect(result).toMatchObject({ type: PipelineResultType.DROP, reason: 'anonymize_failed' })
    })

    it('drops messages whose timestamps are too far from now', async () => {
        const monthAgo = now - 30 * 24 * 60 * 60 * 1000
        addonSuccess({ startTs: monthAgo, endTs: monthAgo + 1000 })
        const result = await step({ message: kafkaMessage(), headers })
        expect(result).toMatchObject({ type: PipelineResultType.DROP, reason: 'message_timestamp_diff_too_large' })
    })

    test.each([
        ['session_id', { sessionId: 'other-session' }, 'session_id_header_body_mismatch'],
        ['distinct_id', { distinctId: 'other-user' }, 'distinct_id_header_body_mismatch'],
    ])('dlqs on a %s header/body mismatch', async (_field, metaOverrides, reason) => {
        addonSuccess(metaOverrides)
        const result = await step({ message: kafkaMessage(), headers })
        expect(result).toMatchObject({ type: PipelineResultType.DLQ, reason })
    })

    it('dlqs when the message value is empty', async () => {
        const result = await step({ message: kafkaMessage(null), headers })
        expect(result).toMatchObject({ type: PipelineResultType.DLQ, reason: 'message_value_or_timestamp_is_empty' })
        expect(mockAnonymizeKafkaPayload).not.toHaveBeenCalled()
    })
})
