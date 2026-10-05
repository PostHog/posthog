import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { APP_METRICS_OUTPUT, DLQ_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { parseJSON } from '~/common/utils/json-parse'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createTestTeam } from '~/tests/helpers/team'

import {
    MetricsIngestionPipelineConfig,
    createMetricsIngestionPipeline,
    runMetricsIngestionPipeline,
} from './metrics-ingestion-pipeline'
import { DEFAULT_METRICS_RETENTION_DAYS, METRICS_OUTPUT } from './outputs/outputs'

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

const METRICS_TOPIC = 'clickhouse_metrics_test'
const DLQ_TOPIC = 'metrics_ingestion_dlq_test'
const APP_METRICS_TOPIC = 'clickhouse_app_metrics2_test'

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

    const createMessage = (token: string | null, recordCount: number): Message => {
        const headers: Record<string, string> = {
            bytes_uncompressed: String(recordCount * 100),
            record_count: String(recordCount),
            created_at: new Date().toISOString(),
        }
        if (token) {
            headers.token = token
        }
        const messageOffset = offset++
        return {
            value: Buffer.from(`opaque avro packet ${messageOffset}`),
            key: null,
            headers: Object.entries(headers).map(([k, v]) => ({ [k]: Buffer.from(v) })),
            topic: 'metrics_ingestion',
            partition: 0,
            offset: messageOffset,
            size: 0,
        }
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
        }
    })

    it('produces each surviving message unchanged and drops the rest silently', async () => {
        const kept = [createMessage(teamA.api_token, 2), createMessage(teamA.api_token, 3)]
        const rateLimited = createMessage(teamA.api_token, 1)
        rateLimiter.filterMessages.mockImplementation((messages: { message: Message }[]) => {
            const dropped = messages.filter((m) => m.message.offset === rateLimited.offset)
            return Promise.resolve({ allowed: messages.filter((m) => !dropped.includes(m)), dropped })
        })

        await runPipeline([
            kept[0],
            createMessage(null, 1),
            createMessage('unknown-token', 1),
            createMessage(teamLimited.api_token, 1),
            rateLimited,
            kept[1],
        ])

        const produced = producedTo(METRICS_TOPIC)
        expect(produced.map((m) => m.value)).toEqual(kept.map((m) => m.value))
        for (const message of produced) {
            expect(message.headers).toMatchObject({
                token: 'token-a',
                team_id: '1',
                'retention-days': String(DEFAULT_METRICS_RETENTION_DAYS),
            })
        }
        expect(producedTo(DLQ_TOPIC)).toHaveLength(0)

        // The rate limiter sees the whole batch once, minus what quota already dropped.
        expect(rateLimiter.filterMessages).toHaveBeenCalledTimes(1)
        expect(rateLimiter.filterMessages.mock.calls[0][0]).toHaveLength(3)
    })

    it('emits one usage row per stat per team', async () => {
        await runPipeline([
            createMessage(teamA.api_token, 2),
            createMessage(teamB.api_token, 1),
            createMessage(teamA.api_token, 1),
            createMessage(teamLimited.api_token, 4),
        ])

        expect(producedTo(METRICS_TOPIC)).toHaveLength(3)
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

    it('sends a message whose produce fails to the DLQ and still emits usage', async () => {
        mockKafkaProducer.produce.mockImplementation((message: { topic: string }) =>
            message.topic === METRICS_TOPIC ? Promise.reject(new Error('broker down')) : Promise.resolve()
        )
        const message = createMessage(teamA.api_token, 2)

        await runPipeline([message])

        const dlq = producedTo(DLQ_TOPIC)
        expect(dlq.map((m) => m.value)).toEqual([message.value])
        expect(dlq[0].headers).toMatchObject({
            token: 'token-a',
            dlq_reason: 'broker down',
            dlq_step: 'produceMetricsStep',
        })
        expect(usageRows()).toEqual(expect.arrayContaining([[1, 'bytes_ingested', 200]]))
    })
})
