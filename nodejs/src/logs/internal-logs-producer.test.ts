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

// Fake timers leave setImmediate real, and it runs after every resolved mock promise in the delivery chain.
const settle = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

function send(producer: InternalLogsProducer, entries: InternalLogEntry[], source = 'hog_flow'): Promise<void> {
    producer.enqueue(source, entries)
    producer.flush()
    return settle()
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
        { name: 'an invalid timestamp, without throwing', entries: [entry({ timestamp: DateTime.invalid('bad') })] },
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
        await Promise.all([first, ...waiting, settle()])
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
            name: 'a team lookup error',
            first: () => teamManager.getTeam.mockRejectedValueOnce(new Error('connection reset')),
            expectedCalls: 1,
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

    it.each([
        { name: 'every request fails', stall: () => fetchMock.mockRejectedValue(new Error('connect ECONNREFUSED')) },
        {
            name: 'the team lookup never answers',
            stall: () => teamManager.getTeam.mockReturnValueOnce(new Promise(() => {})),
        },
    ])('gives up on a batch at the retry timeout when $name', async ({ stall }) => {
        register.resetMetrics()
        stall()
        const producer = new InternalLogsProducer(
            config({ LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS: 2_000 }),
            teamManager
        )

        await send(producer, [entry()])
        await jest.advanceTimersByTimeAsync(5_000)

        const attempts = fetchMock.mock.calls.length
        await jest.advanceTimersByTimeAsync(60_000)
        expect(fetchMock).toHaveBeenCalledTimes(attempts)
        const metric = await register.getSingleMetric('logs_internal_producer_records_total')!.get()
        expect(Object.fromEntries(metric.values.map((v) => [v.labels.outcome, v.value]))).toEqual({ failed: 1 })
        expect((producer as any).inFlight.size).toBe(0)
    })

    it('drain sends entries that were never flushed and waits for them', async () => {
        const held = heldResponse()
        fetchMock.mockReturnValueOnce(held.response)
        const producer = new InternalLogsProducer(config(), teamManager)
        producer.enqueue('hog_flow', [entry()])

        let drained = false
        void producer.drain(10_000).then(() => {
            drained = true
        })
        await jest.advanceTimersByTimeAsync(0)
        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(drained).toBe(false)

        held.release()
        await jest.advanceTimersByTimeAsync(100)
        expect(drained).toBe(true)
    })

    it.each([
        { name: 'a waiting batch', stalledLookup: false },
        { name: 'a team lookup that outlives it', stalledLookup: true },
    ])(
        'drain returns at its timeout, counts every unsent record once as abandoned, and sends nothing after, with $name',
        async ({ stalledLookup }) => {
            register.resetMetrics()
            const held = heldResponse()
            fetchMock.mockReturnValueOnce(held.response)
            let releaseLookup: () => void = () => {}
            if (stalledLookup) {
                const getTeam = teamManager.getTeam.getMockImplementation()!
                teamManager.getTeam
                    .mockImplementationOnce(getTeam)
                    .mockImplementationOnce(
                        (teamId) => new Promise((resolve) => (releaseLookup = () => resolve(getTeam(teamId))))
                    )
            }
            const producer = new InternalLogsProducer(
                config({
                    LOGS_INTERNAL_PRODUCER_TEAMS: '2,3',
                    LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT: stalledLookup ? 2 : 1,
                }),
                teamManager
            )
            void send(producer, [entry()])
            producer.enqueue('hog_flow', [entry({ team_id: 3 })])

            const drain = producer.drain(1_000)
            await jest.advanceTimersByTimeAsync(1_000)

            await expect(drain).resolves.toBeUndefined()
            producer.enqueue('hog_flow', [entry()])
            await producer.drain(1_000)
            held.release()
            releaseLookup()
            await jest.advanceTimersByTimeAsync(10_000)

            expect(fetchMock).toHaveBeenCalledTimes(1)
            const metric = await register.getSingleMetric('logs_internal_producer_records_total')!.get()
            expect(Object.fromEntries(metric.values.map((v) => [v.labels.outcome, v.value]))).toEqual({ abandoned: 3 })
            expect(jest.getTimerCount()).toBe(0)
        }
    )

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

    it.each(Array.from({ length: 20 }, (_, i) => i + 1))(
        'keeps its accounting under random interleavings, seed %i',
        async (seed) => {
            register.resetMetrics()
            let state = seed
            const rand = (): number => {
                state = (state * 1_103_515_245 + 12_345) % 2 ** 31
                return state / 2 ** 31
            }
            const randomSpy = jest.spyOn(Math, 'random').mockImplementation(rand)
            const open: { resolve: (response: any) => void; reject: (error: Error) => void }[] = []
            fetchMock.mockImplementation(() => new Promise((resolve, reject) => open.push({ resolve, reject })))
            const cfg = config({
                LOGS_INTERNAL_PRODUCER_TEAMS: '*',
                LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT: 1 + Math.floor(rand() * 3),
                LOGS_INTERNAL_PRODUCER_MAX_BUFFERED_BYTES: 2_000 + Math.floor(rand() * 20_000),
                LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS: 5_000,
            })
            const producer = new InternalLogsProducer(cfg, teamManager)
            const internals = producer as any
            const counted = async (): Promise<number> => {
                const metric = await register.getSingleMetric('logs_internal_producer_records_total')!.get()
                return metric.values.reduce((sum, v) => sum + v.value, 0)
            }
            let enqueued = 0

            for (let step = 0; step < 150; step++) {
                const op = rand()
                if (op < 0.35) {
                    const entries = Array.from({ length: 1 + Math.floor(rand() * 5) }, () =>
                        entry({ team_id: 1 + Math.floor(rand() * 3), message: 'x'.repeat(Math.floor(rand() * 2_000)) })
                    )
                    producer.enqueue('hog_flow', entries)
                    enqueued += entries.length
                } else if (op < 0.5) {
                    producer.flush()
                } else if (op < 0.75 && open.length > 0) {
                    const { resolve, reject } = open.splice(Math.floor(rand() * open.length), 1)[0]
                    const status = [200, 200, 400, 503, 0][Math.floor(rand() * 5)]
                    if (status === 0) {
                        reject(new Error('reset'))
                    } else {
                        resolve({ status, dump: () => Promise.resolve() })
                    }
                } else if (op < 0.97) {
                    await jest.advanceTimersByTimeAsync(Math.floor(rand() * 3_000))
                } else {
                    void producer.drain(Math.floor(rand() * 2_000))
                }
                await jest.advanceTimersByTimeAsync(0)

                const live = [...internals.waiting.values(), ...internals.inFlight]
                const recordBytes = live.flatMap((b) => b.records).reduce((sum, r) => sum + Buffer.byteLength(r), 0)
                expect(internals.bufferedBytes).toBe(recordBytes)
                expect(internals.bufferedBytes).toBeLessThanOrEqual(cfg.LOGS_INTERNAL_PRODUCER_MAX_BUFFERED_BYTES)
                expect(internals.inFlight.size).toBeLessThanOrEqual(cfg.LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT)
                // A stopped producer already counted its in-flight records as abandoned.
                const held = internals.stopped ? 0 : live.reduce((sum, b) => sum + b.records.length, 0)
                expect((await counted()) + held).toBe(enqueued)
            }

            const drained = producer.drain(0)
            await jest.advanceTimersByTimeAsync(0)
            await drained
            open.splice(0).forEach(({ resolve }) => resolve(ok))
            await jest.advanceTimersByTimeAsync(60_000)
            expect(await counted()).toBe(enqueued)
            randomSpy.mockRestore()
        }
    )
})
