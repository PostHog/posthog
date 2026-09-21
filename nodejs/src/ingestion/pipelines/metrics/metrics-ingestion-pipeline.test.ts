import avro from 'avsc'
import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { APP_METRICS_OUTPUT, DLQ_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { parseJSON } from '~/common/utils/json-parse'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createTestTeam } from '~/tests/helpers/team'

import { decodeMetricsPacket, encodeMetricsPacket } from './metrics-avro'
import {
    MetricsIngestionPipelineConfig,
    createMetricsIngestionPipeline,
    runMetricsIngestionPipeline,
} from './metrics-ingestion-pipeline'
import { METRICS_OUTPUT } from './outputs/outputs'
import { MetricRecord } from './types'

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

const METRICS_TOPIC = 'clickhouse_metrics_test'
const DLQ_TOPIC = 'metrics_ingestion_dlq_test'
const APP_METRICS_TOPIC = 'clickhouse_app_metrics2_test'

const TEST_RECORD_TYPE = avro.Type.forSchema({
    type: 'record',
    name: 'MetricRecord',
    fields: [
        { name: 'metric_name', type: 'string' },
        { name: 'value', type: 'double' },
    ],
})

type ProducedMessage = { topic: string; value: Buffer | null; key: unknown; headers?: Record<string, string> }

describe('MetricsIngestionPipeline', () => {
    const teamA = createTestTeam({ id: 1, api_token: 'token-a' })
    const teamB = createTestTeam({ id: 2, api_token: 'token-b' })
    const teamLimited = createTestTeam({ id: 3, api_token: 'token-limited' })
    const teamByToken = new Map([teamA, teamB, teamLimited].map((team) => [team.api_token, team]))

    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let promiseScheduler: PromiseScheduler
    let rateLimiter: { filterMessages: jest.Mock }
    let config: MetricsIngestionPipelineConfig
    let offset: number

    const records = (prefix: string, count: number): MetricRecord[] =>
        Array.from({ length: count }, (_, i) => ({ metric_name: `${prefix}_${i}`, value: i }))

    const createMessage = async (
        token: string | null,
        rows: MetricRecord[],
        overrides: Partial<Message> = {}
    ): Promise<Message> => {
        const headers: Record<string, string> = {
            bytes_uncompressed: String(rows.length * 100),
            record_count: String(rows.length),
            created_at: new Date().toISOString(),
        }
        if (token) {
            headers.token = token
        }
        return {
            value: await encodeMetricsPacket(TEST_RECORD_TYPE, 'zstandard', rows),
            key: null,
            headers: Object.entries(headers).map(([k, v]) => ({ [k]: Buffer.from(v) })),
            topic: 'metrics_ingestion',
            partition: 0,
            offset: offset++,
            size: 0,
            ...overrides,
        } as Message
    }

    const runPipeline = async (messages: Message[]): Promise<void> => {
        const pipeline = createMetricsIngestionPipeline(config)
        await runMetricsIngestionPipeline(pipeline, messages)
        await promiseScheduler.waitForAll()
    }

    const producedTo = (topic: string): ProducedMessage[] =>
        mockKafkaProducer.produce.mock.calls
            .map(([message]) => message as ProducedMessage)
            .filter((message) => message.topic === topic)

    const usageRows = (): [number, string, number][] =>
        mockKafkaProducer.queueMessages.mock.calls
            .map(([arg]) => arg as { topic: string; messages: { value: Buffer }[] })
            .filter((arg) => arg.topic === APP_METRICS_TOPIC)
            .flatMap((arg) => arg.messages.map((m) => parseJSON(m.value.toString())))
            .map(({ team_id, metric_name, count }) => [team_id, metric_name, count])

    beforeEach(() => {
        offset = 0
        mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
            queueMessages: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<KafkaProducerWrapper>

        promiseScheduler = new PromiseScheduler()
        rateLimiter = {
            filterMessages: jest
                .fn()
                .mockImplementation((messages) => Promise.resolve({ allowed: messages, dropped: [] })),
        }

        config = {
            outputs: new IngestionOutputs({
                [METRICS_OUTPUT]: new SingleIngestionOutput(METRICS_OUTPUT, METRICS_TOPIC, mockKafkaProducer, 'test'),
                [DLQ_OUTPUT]: new SingleIngestionOutput(DLQ_OUTPUT, DLQ_TOPIC, mockKafkaProducer, 'test'),
                [APP_METRICS_OUTPUT]: new SingleIngestionOutput(
                    APP_METRICS_OUTPUT,
                    APP_METRICS_TOPIC,
                    mockKafkaProducer,
                    'test'
                ),
            }),
            promiseScheduler,
            teamManager: {
                getTeam: jest.fn().mockResolvedValue(null),
                getTeamByToken: jest
                    .fn()
                    .mockImplementation((token: string) => Promise.resolve(teamByToken.get(token) ?? null)),
            },
            quotaLimiting: {
                isTeamTokenQuotaLimited: jest
                    .fn()
                    .mockImplementation((token: string) => Promise.resolve(token === teamLimited.api_token)),
            },
            rateLimiter,
            repack: { maxRecordsPerPacket: 1_000_000, maxBytesUncompressedPerPacket: 50 * 1024 * 1024 },
        }
    })

    it('merges the surviving packets of a team into one ClickHouse message and drops the rest silently', async () => {
        const rateLimited = await createMessage(teamA.api_token, records('limited', 1))
        rateLimiter.filterMessages.mockImplementation((messages: { message: Message }[]) => {
            const dropped = messages.filter((m) => m.message.offset === rateLimited.offset)
            return Promise.resolve({ allowed: messages.filter((m) => !dropped.includes(m)), dropped })
        })

        await runPipeline([
            await createMessage(teamA.api_token, records('a', 2)),
            await createMessage(null, records('no_token', 1)),
            await createMessage('unknown-token', records('no_team', 1)),
            await createMessage(teamLimited.api_token, records('quota', 1)),
            rateLimited,
            await createMessage(teamA.api_token, records('b', 3)),
        ])

        const produced = producedTo(METRICS_TOPIC)
        expect(produced).toHaveLength(1)
        expect(produced[0].headers).toMatchObject({
            token: 'token-a',
            team_id: '1',
            record_count: '5',
            repacked_from: '2',
        })
        const decoded = await decodeMetricsPacket(produced[0].value!)
        expect(decoded.records).toEqual([...records('a', 2), ...records('b', 3)])
        expect(producedTo(DLQ_TOPIC)).toHaveLength(0)

        // The rate limiter sees the whole batch once, minus what quota already dropped.
        expect(rateLimiter.filterMessages).toHaveBeenCalledTimes(1)
        expect(rateLimiter.filterMessages.mock.calls[0][0]).toHaveLength(3)
    })

    it('produces one packet per team and one usage row per stat per team', async () => {
        await runPipeline([
            await createMessage(teamA.api_token, records('a', 2)),
            await createMessage(teamB.api_token, records('b', 1)),
            await createMessage(teamA.api_token, records('c', 1)),
            await createMessage(teamLimited.api_token, records('quota', 4)),
        ])

        const produced = producedTo(METRICS_TOPIC)
        expect(produced.map((m) => [m.headers?.team_id, m.headers?.record_count]).sort()).toEqual([
            ['1', '3'],
            ['2', '1'],
        ])
        expect(usageRows().sort()).toEqual(
            [
                [1, 'bytes_received', 300],
                [1, 'records_received', 3],
                [1, 'bytes_ingested', 300],
                [1, 'records_ingested', 3],
                [2, 'bytes_received', 100],
                [2, 'records_received', 1],
                [2, 'bytes_ingested', 100],
                [2, 'records_ingested', 1],
                [3, 'bytes_received', 400],
                [3, 'records_received', 4],
                [3, 'bytes_dropped', 400],
                [3, 'records_dropped', 4],
            ].sort()
        )
    })

    it('sends every original message of a failed packet to the DLQ and still emits usage', async () => {
        mockKafkaProducer.produce.mockImplementation((message: { topic: string }) =>
            message.topic === METRICS_TOPIC ? Promise.reject(new Error('broker down')) : Promise.resolve()
        )
        const first = await createMessage(teamA.api_token, records('a', 1))
        const second = await createMessage(teamA.api_token, records('b', 1))

        await runPipeline([first, second])

        const dlq = producedTo(DLQ_TOPIC)
        expect(dlq.map((m) => m.value)).toEqual(expect.arrayContaining([first.value, second.value]))
        expect(dlq).toHaveLength(2)
        for (const message of dlq) {
            expect(message.headers).toMatchObject({
                token: 'token-a',
                dlq_reason: 'broker down',
                dlq_step: 'repackAndProduceMetricsStep',
            })
        }
        expect(usageRows()).toEqual(expect.arrayContaining([[1, 'bytes_ingested', 200]]))
    })

    it('sends an undecodable packet to the DLQ without blocking the rest of the team', async () => {
        const broken = await createMessage(teamA.api_token, [], { value: Buffer.from('not avro') })
        const good = await createMessage(teamA.api_token, records('a', 2))

        await runPipeline([broken, good])

        expect(producedTo(DLQ_TOPIC).map((m) => m.headers?.dlq_step)).toEqual(['decodeMetricsPacketStep'])
        expect(producedTo(METRICS_TOPIC).map((m) => m.headers?.record_count)).toEqual(['2'])
    })
})
