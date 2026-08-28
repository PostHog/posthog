import { Message } from 'node-rdkafka'
import { promisify } from 'node:util'
import { register } from 'prom-client'
import { gzip } from 'zlib'

import { PipelineResultType } from '~/ingestion/framework/results'
import { imageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'
import { SessionReplayHeaders } from '~/ingestion/pipelines/sessionreplay/pipeline-types'

import { createParseAndAnonymizeMessageStep } from './parse-and-anonymize-step'
import {
    PSEUDONYM_IMAGE_CONTENT_KEY,
    PSEUDONYM_IMAGE_URL_GLOBAL_VALUE,
    PSEUDONYM_IMAGE_URL_KEY,
    PSEUDONYM_TEAM,
    pseudonymize,
} from './pseudonymize'

const compressWithGzip = promisify(gzip)
const IMAGE_SOURCE_METRIC = 'recording_blob_ingestion_v2_ml_image_references_by_property'

async function imageSourceMetricValue(source: string, property: string, kind: string): Promise<number> {
    const metric = register.getSingleMetric(IMAGE_SOURCE_METRIC)
    if (!metric) {
        return 0
    }
    const { values } = await metric.get()
    return (
        values.find(
            (value) =>
                value.labels.source === source && value.labels.property === property && value.labels.kind === kind
        )?.value ?? 0
    )
}

// The native addon is the mocked boundary: these tests pin the TS side of the fused step — failure
// classification (dlq vs drop), the timestamp window, header/body agreement, and the ParsedMessageData
// assembly — not the scrub itself (that's covered by the Rust suite + shared fixtures).
const mockAnonymizeKafkaPayload = jest.fn()
jest.mock('@posthog/replay-anonymizer', () => ({
    anonymizeKafkaPayload: (
        payload: Buffer,
        contentEncoding?: string | null,
        pseudoTeam?: string | null,
        contentKey?: string | null,
        urlKey?: string | null
    ) => mockAnonymizeKafkaPayload(payload, contentEncoding, pseudoTeam, contentKey, urlKey),
}))

describe('createParseAndAnonymizeMessageStep', () => {
    const step = createParseAndAnonymizeMessageStep()
    const now = Date.now()

    const team = {
        teamId: 1,
        consoleLogIngestionEnabled: true,
        aiTrainingOptedIn: true,
    }

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

    function addonSuccess(metaOverrides: Record<string, unknown> = {}, images: Buffer | null = null): void {
        mockAnonymizeKafkaPayload.mockResolvedValue({
            failed: false,
            reason: null,
            error: null,
            lines: Buffer.from('["window-1",{"type":3,"timestamp":' + now + '}]\n'),
            images,
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
        const result = await step({ message: kafkaMessage(), headers, team })

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
            team,
        })
        expect(result.type).toBe(PipelineResultType.OK)
        expect((result as any).value.parsedMessage.session_id).toBe(upper.toLowerCase())
    })

    it('hands the addon the raw bytes and content encoding (decompression lives in Rust)', async () => {
        addonSuccess()
        const raw = Buffer.from(JSON.stringify({ distinct_id: 'user-1', data: '{}' }))
        const zipped = await compressWithGzip(raw)
        await step({ message: kafkaMessage(zipped), headers, team })
        expect(mockAnonymizeKafkaPayload).toHaveBeenCalledWith(zipped, null, undefined, undefined, undefined)

        mockAnonymizeKafkaPayload.mockClear()
        addonSuccess()
        const lz4Message = kafkaMessage(raw)
        lz4Message.headers = [{ 'content-encoding': Buffer.from('lz4') }]
        await step({ message: lz4Message, headers, team })
        expect(mockAnonymizeKafkaPayload).toHaveBeenCalledWith(raw, 'lz4', undefined, undefined, undefined)
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
        const result = await step({ message: kafkaMessage(), headers, team })
        expect(result.type).toBe(expectedType)
        expect((result as any).reason).toBe(reason)
    })

    it('fails closed when the addon promise rejects', async () => {
        mockAnonymizeKafkaPayload.mockRejectedValue(new Error('native panic'))
        const result = await step({ message: kafkaMessage(), headers, team })
        expect(result).toMatchObject({ type: PipelineResultType.DROP, reason: 'anonymize_failed' })
    })

    it('drops messages whose timestamps are too far from now', async () => {
        const monthAgo = now - 30 * 24 * 60 * 60 * 1000
        addonSuccess({ startTs: monthAgo, endTs: monthAgo + 1000 })
        const result = await step({ message: kafkaMessage(), headers, team })
        expect(result).toMatchObject({ type: PipelineResultType.DROP, reason: 'message_timestamp_diff_too_large' })
    })

    test.each([
        ['session_id', { sessionId: 'other-session' }, 'session_id_header_body_mismatch'],
        ['distinct_id', { distinctId: 'other-user' }, 'distinct_id_header_body_mismatch'],
    ])('dlqs on a %s header/body mismatch', async (_field, metaOverrides, reason) => {
        addonSuccess(metaOverrides)
        const result = await step({ message: kafkaMessage(), headers, team })
        expect(result).toMatchObject({ type: PipelineResultType.DLQ, reason })
    })

    it('dlqs when the message value is empty', async () => {
        const result = await step({ message: kafkaMessage(null), headers, team })
        expect(result).toMatchObject({ type: PipelineResultType.DLQ, reason: 'message_value_or_timestamp_is_empty' })
        expect(mockAnonymizeKafkaPayload).not.toHaveBeenCalled()
    })
})

describe('createParseAndAnonymizeMessageStep with image collection', () => {
    const secret = 'test-pseudonym-secret'
    const step = createParseAndAnonymizeMessageStep({
        pseudonymSecret: secret,
        collectImages: true,
        collectUrls: false,
    })
    const pseudoTeam = pseudonymize(secret, PSEUDONYM_TEAM, '1')
    const contentKey = pseudonymize(secret, PSEUDONYM_IMAGE_CONTENT_KEY, '1')
    const now = Date.now()

    const team = {
        teamId: 1,
        consoleLogIngestionEnabled: true,
        aiTrainingOptedIn: true,
    }
    const headers: SessionReplayHeaders = {
        token: 'token-1',
        distinct_id: 'user-1',
        session_id: 'session-1',
    } as SessionReplayHeaders

    function kafkaMessage(): Message {
        return {
            value: Buffer.from('{}'),
            timestamp: now,
            partition: 3,
            topic: 'snapshots',
            offset: 42,
            size: 2,
        } as Message
    }

    function addonSuccessWithImages(
        images: Buffer | null,
        imageEntries?: { hash: string; offset: number; len: number }[],
        imageSources?: { source: 'css' | 'html'; property: string; kind: 'inline' | 'url'; count: number }[]
    ): void {
        mockAnonymizeKafkaPayload.mockResolvedValue({
            failed: false,
            reason: null,
            error: null,
            lines: Buffer.from('["window-1",{"type":3,"timestamp":' + now + '}]\n'),
            images,
            meta: JSON.stringify({
                distinctId: 'user-1',
                sessionId: 'session-1',
                windowId: 'window-1',
                snapshotSource: 'web',
                snapshotLibrary: 'posthog-js',
                startTs: now,
                endTs: now + 1000,
                consoleLogCount: 0,
                consoleWarnCount: 0,
                consoleErrorCount: 0,
                events: [{ ts: now, flags: 0 }],
                images: imageEntries,
                imageSources,
            }),
        })
    }

    beforeEach(() => {
        mockAnonymizeKafkaPayload.mockReset()
    })

    it('passes the cached per-team pseudonym and content key to the addon', async () => {
        addonSuccessWithImages(null)
        await step({ message: kafkaMessage(), headers, team })
        await step({ message: kafkaMessage(), headers, team })
        expect(mockAnonymizeKafkaPayload).toHaveBeenCalledTimes(2)
        for (const call of mockAnonymizeKafkaPayload.mock.calls) {
            expect(call[2]).toBe(pseudoTeam)
            expect(call[3]).toBe(contentKey)
            expect(call[3]).not.toBe(call[2])
        }
    })

    it('unpacks the packed image buffer into per-image produce records', async () => {
        const packed = Buffer.concat([Buffer.from('aaa'), Buffer.from('bb')])
        addonSuccessWithImages(packed, [
            { hash: 'hashA', offset: 0, len: 3 },
            { hash: 'hashB', offset: 3, len: 2 },
        ])
        const result = await step({ message: kafkaMessage(), headers, team })
        expect(result.type).toBe(PipelineResultType.OK)
        const images = (result as any).value.collectedImages
        expect(images).toEqual([
            { ref: imageRef(pseudoTeam, 'hashA'), bytes: Buffer.from('aaa') },
            { ref: imageRef(pseudoTeam, 'hashB'), bytes: Buffer.from('bb') },
        ])
    })

    it('skips out-of-bounds entries instead of failing the message', async () => {
        addonSuccessWithImages(Buffer.from('aaa'), [
            { hash: 'hashA', offset: 0, len: 3 },
            { hash: 'hashBad', offset: 2, len: 5 },
        ])
        const result = await step({ message: kafkaMessage(), headers, team })
        expect(result.type).toBe(PipelineResultType.OK)
        expect((result as any).value.collectedImages).toEqual([
            { ref: imageRef(pseudoTeam, 'hashA'), bytes: Buffer.from('aaa') },
        ])
    })

    it('leaves collectedImages undefined when the addon collected nothing', async () => {
        addonSuccessWithImages(null)
        const result = await step({ message: kafkaMessage(), headers, team })
        expect(result.type).toBe(PipelineResultType.OK)
        expect((result as any).value.collectedImages).toBeUndefined()
    })

    it('records bounded CSS and HTML image source counts', async () => {
        const cssBefore = await imageSourceMetricValue('css', 'background-image', 'inline')
        const htmlBefore = await imageSourceMetricValue('html', 'src', 'url')
        addonSuccessWithImages(
            Buffer.from('a'),
            [{ hash: 'hashA', offset: 0, len: 1 }],
            [
                { source: 'css', property: 'background-image', kind: 'inline', count: 3 },
                { source: 'html', property: 'src', kind: 'url', count: 2 },
            ]
        )

        await step({ message: kafkaMessage(), headers, team })

        await expect(imageSourceMetricValue('css', 'background-image', 'inline')).resolves.toBe(cssBefore + 3)
        await expect(imageSourceMetricValue('html', 'src', 'url')).resolves.toBe(htmlBefore + 2)
    })
})

describe('createParseAndAnonymizeMessageStep with url collection', () => {
    const secret = 'test-pseudonym-secret'
    const pseudoTeam = pseudonymize(secret, PSEUDONYM_TEAM, '1')
    const urlKey = pseudonymize(secret, PSEUDONYM_IMAGE_URL_KEY, PSEUDONYM_IMAGE_URL_GLOBAL_VALUE)
    const now = Date.now()
    const team = { teamId: 1, consoleLogIngestionEnabled: true, aiTrainingOptedIn: true }
    const headers: SessionReplayHeaders = {
        token: 'token',
        distinct_id: 'distinct-id',
        session_id: 'session-id',
    } as SessionReplayHeaders

    const kafkaMessage = (): any => ({
        value: Buffer.from('payload'),
        timestamp: now,
        partition: 0,
        topic: 't',
        offset: 1,
        size: 7,
    })

    const meta = (urls?: unknown[]): string =>
        JSON.stringify({
            distinctId: 'distinct-id',
            sessionId: 'session-id',
            windowId: 'w',
            snapshotSource: null,
            snapshotLibrary: null,
            startTs: now,
            endTs: now,
            consoleLogCount: 0,
            consoleWarnCount: 0,
            consoleErrorCount: 0,
            events: [],
            ...(urls ? { urls } : {}),
        })

    beforeEach(() => mockAnonymizeKafkaPayload.mockReset())

    it('uses one global URL key and ref for every team', async () => {
        // The URL lane measures before any topic exists. Requiring the image lane to be on first
        // would make that measurement impossible to take on its own.
        mockAnonymizeKafkaPayload.mockResolvedValue({
            failed: false,
            lines: Buffer.from(''),
            meta: meta([{ hash: 'h'.repeat(22), url: 'https://cdn.example.com/a.png', host: 'cdn.example.com' }]),
            images: null,
        })
        const step = createParseAndAnonymizeMessageStep({
            pseudonymSecret: secret,
            collectImages: false,
            collectUrls: true,
        })

        const result: any = await step({ message: kafkaMessage(), headers, team } as any)
        const otherTeam = { ...team, teamId: 2 }
        const otherResult: any = await step({ message: kafkaMessage(), headers, team: otherTeam } as any)

        expect(mockAnonymizeKafkaPayload).toHaveBeenCalledWith(expect.anything(), null, pseudoTeam, undefined, urlKey)
        expect(result.value.collectedUrls).toEqual([
            {
                ref: `imageurl:${'h'.repeat(22)}`,
                pseudoTeam,
                url: 'https://cdn.example.com/a.png',
                host: 'cdn.example.com',
            },
        ])
        expect(mockAnonymizeKafkaPayload).toHaveBeenLastCalledWith(
            expect.anything(),
            null,
            pseudonymize(secret, PSEUDONYM_TEAM, '2'),
            undefined,
            urlKey
        )
        expect(otherResult.value.collectedUrls[0].ref).toBe(result.value.collectedUrls[0].ref)
        expect(result.value.collectedImages).toBeUndefined()
    })

    it('passes no keys at all when both lanes are off', async () => {
        mockAnonymizeKafkaPayload.mockResolvedValue({
            failed: false,
            lines: Buffer.from(''),
            meta: meta(),
            images: null,
        })
        const step = createParseAndAnonymizeMessageStep({
            pseudonymSecret: secret,
            collectImages: false,
            collectUrls: false,
        })

        await step({ message: kafkaMessage(), headers, team } as any)

        expect(mockAnonymizeKafkaPayload).toHaveBeenCalledWith(
            expect.anything(),
            null,
            pseudoTeam,
            undefined,
            undefined
        )
    })
})
