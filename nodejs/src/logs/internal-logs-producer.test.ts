import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import { InternalLogsVerifier } from './internal-logs'
import { InternalLogRecord, InternalLogsProducer, InternalLogsProducerConfig } from './internal-logs-producer'

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

function record(overrides: Partial<InternalLogRecord> = {}): InternalLogRecord {
    return {
        source: 'hog_flow',
        teamId: 2,
        timestamp: DateTime.fromISO('2026-10-27T12:00:00.123Z'),
        level: 'warn',
        message: 'Email step skipped',
        attributes: { log_source_id: 'flow-1', instance_id: 'run-1' },
        ...overrides,
    }
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
        await new InternalLogsProducer(config(), teamManager).send([record()])

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
            { key: 'service.name', value: { stringValue: 'posthog-workflows' } },
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
        await new InternalLogsProducer(config({ LOGS_INTERNAL_PRODUCER_TEAMS: '2,3' }), teamManager).send([
            record({ teamId: 2 }),
            record({ teamId: 3 }),
            record({ teamId: 2, message: 'second' }),
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
        { name: 'a team not on the allowlist', records: [record({ teamId: 3 })] },
        { name: 'a source with no policy', records: [record({ source: 'hog_function' })] },
        { name: 'no endpoint', overrides: { LOGS_INTERNAL_PRODUCER_URL: '' }, records: [record()] },
        { name: 'no signing key', overrides: { LOGS_INTERNAL_INGESTION_SIGNING_KEYS: ' ' }, records: [record()] },
        { name: 'an empty allowlist', overrides: { LOGS_INTERNAL_PRODUCER_TEAMS: '' }, records: [record()] },
    ])('sends nothing for $name', async ({ overrides = {}, records }) => {
        await new InternalLogsProducer(config(overrides), teamManager).send(records)

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

        const first = producer.send([record()])
        await producer.send([record()])
        expect(fetchMock).toHaveBeenCalledTimes(1)

        release()
        await first
        await producer.send([record()])
        expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('resolves when capture-logs is unreachable', async () => {
        fetchMock.mockRejectedValueOnce(new Error('connect ECONNREFUSED'))

        await expect(new InternalLogsProducer(config(), teamManager).send([record()])).resolves.toBeUndefined()
    })
})
