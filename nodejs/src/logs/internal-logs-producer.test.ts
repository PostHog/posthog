import { DateTime } from 'luxon'
import { register } from 'prom-client'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import { InternalLogsVerifier } from './internal-logs'
import { InternalLogEntry, InternalLogsProducer, InternalLogsProducerConfig } from './internal-logs-producer'

jest.mock('~/common/utils/request', () => ({ internalFetch: jest.fn() }))

const KEY = 'internal-logs-test-key'
const URL = 'http://capture-logs.test/i/v1/logs'
const SIGNED_AT = new Date('2026-10-27T12:00:00Z')

const fetchMock = jest.mocked(internalFetch)

function config(overrides: Partial<InternalLogsProducerConfig> = {}): InternalLogsProducerConfig {
    return {
        LOGS_INTERNAL_INGESTION_SIGNING_KEYS: KEY,
        LOGS_INTERNAL_PRODUCER_URL: URL,
        LOGS_INTERNAL_PRODUCER_TEAMS: '2',
        LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT: 20,
        LOGS_INTERNAL_PRODUCER_MAX_BUFFERED_BYTES: 64 * 1024 * 1024,
        LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS: 60_000,
        ...overrides,
    }
}

const teamManager = {
    getTeam: jest.fn((teamId: number) => Promise.resolve({ id: teamId, api_token: `phc_team_${teamId}` } as any)),
}

function entry(overrides: Partial<InternalLogEntry> = {}): InternalLogEntry {
    return {
        team_id: 2,
        log_source_id: 'flow-1',
        instance_id: 'run-1',
        timestamp: DateTime.fromISO('2026-10-27T12:00:00.123Z'),
        level: 'warn',
        message: 'Email step skipped',
        ...overrides,
    }
}

function send(producer: InternalLogsProducer, entries: InternalLogEntry[], source = 'hog_flow'): Promise<void> {
    producer.enqueue(source, entries)
    return producer.flush()
}

const ok = { status: 200, dump: () => Promise.resolve() } as any

function heldResponse(): { response: Promise<any>; release: () => void } {
    let release: () => void = () => {}
    const response = new Promise((resolve) => {
        release = () => resolve(ok)
    })
    return { response, release }
}

describe('InternalLogsProducer', () => {
    beforeEach(() => {
        jest.useFakeTimers({ now: SIGNED_AT, doNotFake: ['nextTick', 'setImmediate'] })
        fetchMock.mockReset()
        fetchMock.mockResolvedValue({ status: 200, dump: () => Promise.resolve() } as any)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('sends a batch the logs consumer verifies as internal', async () => {
        await send(new InternalLogsProducer(config(), teamManager), [entry()])

        expect(fetchMock).toHaveBeenCalledTimes(1)
        const [url, options] = fetchMock.mock.calls[0]
        const headers = options!.headers as Record<string, string>
        expect(url).toEqual(URL)
        expect(headers.Authorization).toEqual('Bearer phc_team_2')
        const verifier = new InternalLogsVerifier(KEY, '2')
        expect(verifier.verify(headers['x-posthog-internal'], 2, SIGNED_AT.toISOString())).toEqual({
            source: 'hog_flow',
            billed: false,
            teamRules: false,
        })

        const body = parseJSON(options!.body as string) as any
        expect(body.resourceLogs[0].resource.attributes).toEqual([
            { key: 'service.name', value: { stringValue: 'posthog-internal-workflows' } },
        ])
        expect(body.resourceLogs[0].scopeLogs[0].logRecords).toEqual([
            {
                timeUnixNano: '1793102400123000000',
                severityText: 'WARN',
                severityNumber: 13,
                body: { stringValue: 'Email step skipped' },
                attributes: [
                    { key: 'log_source_id', value: { stringValue: 'flow-1' } },
                    { key: 'instance_id', value: { stringValue: 'run-1' } },
                ],
            },
        ])
    })

    it('sends one request per team, each signed for its own team', async () => {
        await send(new InternalLogsProducer(config({ LOGS_INTERNAL_PRODUCER_TEAMS: '2,3' }), teamManager), [
            entry({ team_id: 2 }),
            entry({ team_id: 3 }),
            entry({ team_id: 2, message: 'second' }),
        ])

        const sent = fetchMock.mock.calls.map(([, options]) => {
            const headers = options!.headers as Record<string, string>
            const body = parseJSON(options!.body as string) as any
            return { token: headers.Authorization, records: body.resourceLogs[0].scopeLogs[0].logRecords.length }
        })
        expect(sent).toEqual([
            { token: 'Bearer phc_team_2', records: 2 },
            { token: 'Bearer phc_team_3', records: 1 },
        ])
        const verifier = new InternalLogsVerifier(KEY, '*')
        const team3Signature = (fetchMock.mock.calls[1][1]!.headers as Record<string, string>)['x-posthog-internal']
        expect(verifier.verify(team3Signature, 3, SIGNED_AT.toISOString())).toBeDefined()
        expect(verifier.verify(team3Signature, 2, SIGNED_AT.toISOString())).toBeUndefined()
    })

    it.each([
        { name: 'a team not on the allowlist', entries: [entry({ team_id: 3 })] },
        { name: 'a source with no policy', source: 'hog_function', entries: [entry()] },
        { name: 'no endpoint', overrides: { LOGS_INTERNAL_PRODUCER_URL: '' }, entries: [entry()] },
        { name: 'no signing key', overrides: { LOGS_INTERNAL_INGESTION_SIGNING_KEYS: ' ' }, entries: [entry()] },
        { name: 'an empty allowlist', overrides: { LOGS_INTERNAL_PRODUCER_TEAMS: '' }, entries: [entry()] },
    ])('sends nothing for $name', async ({ overrides = {}, source, entries }) => {
        await send(new InternalLogsProducer(config(overrides), teamManager), entries, source)

        expect(fetchMock).not.toHaveBeenCalled()
    })

    it.each([
        {
            name: 'waits, then leaves with the other waiting batches in one request',
            maxBufferedBytes: 64 * 1024 * 1024,
            expectedCalls: 2,
        },
        { name: 'is dropped when the buffer is full', maxBufferedBytes: 15_000, expectedCalls: 1 },
    ])('a batch over the in-flight cap $name', async ({ maxBufferedBytes, expectedCalls }) => {
        const held = heldResponse()
        fetchMock.mockReturnValueOnce(held.response)
        const producer = new InternalLogsProducer(
            config({
                LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT: 1,
                LOGS_INTERNAL_PRODUCER_MAX_BUFFERED_BYTES: maxBufferedBytes,
            }),
            teamManager
        )
        const message = 'x'.repeat(10_000)

        const first = send(producer, [entry({ message })])
        const waiting = [send(producer, [entry({ message })]), send(producer, [entry({ message })])]
        await jest.advanceTimersByTimeAsync(0)
        expect(fetchMock).toHaveBeenCalledTimes(1)

        held.release()
        await Promise.all([first, ...waiting])
        expect(fetchMock).toHaveBeenCalledTimes(expectedCalls)
    })

    it.each([
        {
            name: 'a 503',
            first: () => fetchMock.mockResolvedValueOnce({ status: 503, dump: () => Promise.resolve() } as any),
            expectedCalls: 2,
        },
        {
            name: 'a 429',
            first: () => fetchMock.mockResolvedValueOnce({ status: 429, dump: () => Promise.resolve() } as any),
            expectedCalls: 2,
        },
        {
            name: 'a network error',
            first: () => fetchMock.mockRejectedValueOnce(new Error('connect ECONNREFUSED')),
            expectedCalls: 2,
        },
        {
            name: 'a 400',
            first: () => fetchMock.mockResolvedValueOnce({ status: 400, dump: () => Promise.resolve() } as any),
            expectedCalls: 1,
        },
    ])('after $name, sends $expectedCalls request(s)', async ({ first, expectedCalls }) => {
        first()

        const sent = send(new InternalLogsProducer(config(), teamManager), [entry()])
        await jest.advanceTimersByTimeAsync(10_000)
        await sent

        expect(fetchMock).toHaveBeenCalledTimes(expectedCalls)
    })

    it('signs each retry again, so a request that hung past the signature window does not make the retry billed', async () => {
        const retriedAt = new Date(SIGNED_AT.getTime() + 10 * 60 * 1000)
        fetchMock.mockImplementationOnce(() => {
            jest.setSystemTime(retriedAt)
            return Promise.reject(new Error('socket hang up'))
        })

        const sent = send(
            new InternalLogsProducer(config({ LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS: 30 * 60 * 1000 }), teamManager),
            [entry()]
        )
        await jest.advanceTimersByTimeAsync(10_000)
        await sent

        expect(fetchMock).toHaveBeenCalledTimes(2)
        const retrySignature = (fetchMock.mock.calls[1][1]!.headers as Record<string, string>)['x-posthog-internal']
        expect(new InternalLogsVerifier(KEY, '2').verify(retrySignature, 2, retriedAt.toISOString())).toBeDefined()
    })

    it('gives up on a batch at the retry timeout', async () => {
        fetchMock.mockRejectedValue(new Error('connect ECONNREFUSED'))

        const sent = send(
            new InternalLogsProducer(config({ LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS: 2_000 }), teamManager),
            [entry()]
        )
        await jest.advanceTimersByTimeAsync(5_000)

        await expect(sent).resolves.toBeUndefined()
        const attempts = fetchMock.mock.calls.length
        await jest.advanceTimersByTimeAsync(60_000)
        expect(fetchMock).toHaveBeenCalledTimes(attempts)
    })

    it('drain sends entries that were never flushed and waits for them', async () => {
        const held = heldResponse()
        fetchMock.mockReturnValueOnce(held.response)
        const producer = new InternalLogsProducer(config(), teamManager)
        producer.enqueue('hog_flow', [entry()])

        let drained = false
        const drain = producer.drain(10_000).then(() => {
            drained = true
        })
        await jest.advanceTimersByTimeAsync(0)
        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(drained).toBe(false)

        held.release()
        await drain
        expect(drained).toBe(true)
    })

    it('drain returns at its timeout and counts every unsent batch as abandoned', async () => {
        register.resetMetrics()
        fetchMock.mockReturnValueOnce(heldResponse().response)
        const producer = new InternalLogsProducer(
            config({ LOGS_INTERNAL_PRODUCER_TEAMS: '2,3', LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT: 1 }),
            teamManager
        )
        void send(producer, [entry()])
        producer.enqueue('hog_flow', [entry({ team_id: 3 })])

        const drain = producer.drain(1_000)
        await jest.advanceTimersByTimeAsync(1_000)

        await expect(drain).resolves.toBeUndefined()
        const metric = await register.getSingleMetric('logs_internal_producer_batches_total')!.get()
        expect(metric.values.find((v) => v.labels.outcome === 'abandoned')?.value).toBe(2)
    })

    it('splits a large team batch into requests under the capture-logs body limit', async () => {
        const message = 'x'.repeat(10_000)
        await send(
            new InternalLogsProducer(config(), teamManager),
            Array.from({ length: 250 }, () => entry({ message }))
        )

        const bodies = fetchMock.mock.calls.map(([, options]) => options!.body as string)
        expect(bodies.length).toBeGreaterThan(1)
        for (const body of bodies) {
            expect(Buffer.byteLength(body)).toBeLessThan(2 * 1024 * 1024)
        }
        const sent = bodies.map((body) => (parseJSON(body) as any).resourceLogs[0].scopeLogs[0].logRecords.length)
        expect(sent.reduce((a, b) => a + b, 0)).toEqual(250)
    })

    it('cuts a message too large for one request, so capture-logs still accepts the record', async () => {
        await send(new InternalLogsProducer(config(), teamManager), [entry({ message: '"'.repeat(3 * 1024 * 1024) })])

        expect(fetchMock).toHaveBeenCalledTimes(1)
        const body = fetchMock.mock.calls[0][1]!.body as string
        expect(Buffer.byteLength(body)).toBeLessThan(2 * 1024 * 1024)
        expect((parseJSON(body) as any).resourceLogs[0].scopeLogs[0].logRecords[0].body.stringValue).toEqual(
            '"'.repeat(128 * 1024)
        )
    })

    it('replaces an unpaired surrogate so capture-logs can decode the rest of the batch', async () => {
        await send(new InternalLogsProducer(config(), teamManager), [
            entry({ message: '😀'.substring(0, 1) }),
            entry({ message: 'valid' }),
        ])

        const body = fetchMock.mock.calls[0][1]!.body as string
        const messages = (parseJSON(body) as any).resourceLogs[0].scopeLogs[0].logRecords.map(
            (r: any) => r.body.stringValue
        )
        expect(messages).toEqual(['\uFFFD', 'valid'])
    })
})
