import { DateTime } from 'luxon'

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

    it('drops a batch over the in-flight cap instead of waiting', async () => {
        let release: () => void = () => {}
        fetchMock.mockReturnValueOnce(
            new Promise((resolve) => {
                release = () => resolve({ status: 200, dump: () => Promise.resolve() } as any)
            })
        )
        const producer = new InternalLogsProducer(config({ LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT: 1 }), teamManager)

        const first = send(producer, [entry()])
        await send(producer, [entry()])
        expect(fetchMock).toHaveBeenCalledTimes(1)

        release()
        await first
        await send(producer, [entry()])
        expect(fetchMock).toHaveBeenCalledTimes(2)
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

    it('resolves when capture-logs is unreachable', async () => {
        fetchMock.mockRejectedValueOnce(new Error('connect ECONNREFUSED'))

        await expect(send(new InternalLogsProducer(config(), teamManager), [entry()])).resolves.toBeUndefined()
    })
})
