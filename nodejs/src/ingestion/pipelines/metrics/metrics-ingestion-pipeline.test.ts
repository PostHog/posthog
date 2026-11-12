import avro from 'avsc'
import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { APP_METRICS_OUTPUT, DLQ_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { parseJSON } from '~/common/utils/json-parse'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { PipelineResultType } from '~/ingestion/framework/results'
import { createTestTeam } from '~/tests/helpers/team'

import { createAggregateMetricsStep } from './aggregate-metrics-step'
import { decodeMetricRecords, encodeMetricRecords, parseWriterSchema, unwrap } from './metric-record-avro'
import {
    MetricsIngestionPipelineConfig,
    createMetricsIngestionPipeline,
    runMetricsIngestionPipeline,
} from './metrics-ingestion-pipeline'
import { emitMetricsUsage } from './metrics-usage-steps'
import { DEFAULT_METRICS_RETENTION_DAYS, METRICS_OUTPUT } from './outputs/outputs'

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

const METRICS_TOPIC = 'clickhouse_metrics_test'
const DLQ_TOPIC = 'metrics_ingestion_dlq_test'
const APP_METRICS_TOPIC = 'clickhouse_app_metrics2_test'

const NULLABLE_LONG = ['null', 'long']
const METRIC_SCHEMA: avro.Schema = {
    type: 'record',
    name: 'MetricRecord',
    fields: [
        { name: 'timestamp', type: ['null', { type: 'long', logicalType: 'timestamp-micros' }] },
        { name: 'metric_type', type: ['null', 'string'] },
        { name: 'value', type: ['null', 'double'] },
        { name: 'count', type: NULLABLE_LONG },
        { name: 'aggregation_temporality', type: ['null', 'string'] },
        { name: 'is_monotonic', type: ['null', 'boolean'] },
        { name: 'series_fingerprint', type: NULLABLE_LONG, default: null },
    ],
}
const METRIC_CONTAINER = {
    type: parseWriterSchema(METRIC_SCHEMA),
    meta: { 'avro.schema': Buffer.from(JSON.stringify(METRIC_SCHEMA)) },
    codec: 'zstandard',
}
const FINGERPRINT = -6_000_000_000_000_000_123n

const metricPoint = (metricType: string, value: number, microsIntoBucket: bigint) => ({
    timestamp: { long: 1_700_000_010_000_000n + microsIntoBucket },
    metric_type: { string: metricType },
    value: { double: value },
    count: { long: 1n },
    aggregation_temporality: { string: 'delta' },
    is_monotonic: { boolean: true },
    series_fingerprint: { long: FINGERPRINT },
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

    const createMessage = (token: string | null, recordCount: number): Message => {
        const headers: Record<string, string> = {
            bytes_uncompressed: String(recordCount * 100),
            bytes_uncompressed_records: String(recordCount * 250),
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
        const usage = await runMetricsIngestionPipeline(pipeline, messages)
        await promiseScheduler.waitForAll()
        await emitMetricsUsage(
            config.outputs,
            new UsageRecordBatch(null, { unit: 'bytes', isTeamEnabled: () => false }),
            usage
        )
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
            isAggregationEnabled: () => false,
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
                [1, 'bytes_ingested_records', 750],
                [1, 'records_ingested', 3],
                [2, 'bytes_received', 100],
                [2, 'records_received', 1],
                [2, 'bytes_ingested', 100],
                [2, 'bytes_ingested_records', 250],
                [2, 'records_ingested', 1],
                [3, 'bytes_received', 400],
                [3, 'records_received', 4],
                [3, 'bytes_dropped', 400],
                [3, 'records_dropped', 4],
            ].sort()
        )
    })

    it('finishes the batch before the ClickHouse-bound produce is acked', async () => {
        let ack: () => void = () => {}
        mockKafkaProducer.produce.mockReturnValueOnce(new Promise<void>((resolve) => (ack = resolve)))
        const pipeline = createMetricsIngestionPipeline(config)

        await runMetricsIngestionPipeline(pipeline, [createMessage(teamA.api_token, 2)])

        let drained = false
        const drain = promiseScheduler.waitForAll().then(() => (drained = true))
        await new Promise((resolve) => setImmediate(resolve))
        expect(drained).toBe(false)

        ack()
        await drain
        expect(producedTo(METRICS_TOPIC)).toHaveLength(1)
    })

    it('sends a message whose produce fails permanently to the DLQ and still emits usage', async () => {
        mockKafkaProducer.produce.mockImplementation((message: { topic: string }) =>
            message.topic === METRICS_TOPIC
                ? Promise.reject(new MessageSizeTooLarge('too large', new Error('too large')))
                : Promise.resolve()
        )
        const message = createMessage(teamA.api_token, 2)

        await runPipeline([message])

        const dlq = producedTo(DLQ_TOPIC)
        expect(dlq.map((m) => m.value)).toEqual([message.value])
        expect(dlq[0].headers).toMatchObject({
            token: 'token-a',
            team_id: '1',
            dlq_reason: 'too large',
            dlq_step: 'produceMetricsStep',
        })
        expect(usageRows()).toEqual(expect.arrayContaining([[1, 'bytes_ingested', 200]]))
    })

    it('merges the sum points of an enabled team into fewer messages and keeps the usage totals', async () => {
        config.isAggregationEnabled = (teamId) => teamId === teamA.id
        const first = createMessage(teamA.api_token, 2)
        first.value = await encodeMetricRecords(METRIC_CONTAINER, [
            metricPoint('gauge', 3, 1n),
            metricPoint('sum', 10, 1n),
        ])
        const second = createMessage(teamA.api_token, 1)
        second.value = await encodeMetricRecords(METRIC_CONTAINER, [metricPoint('sum', 10, 2n)])

        await runPipeline([first, second])

        const produced = producedTo(METRICS_TOPIC)
        expect(produced).toHaveLength(1)
        const decoded = await decodeMetricRecords(produced[0].value!)
        expect(decoded.meta['avro.schema'].toString()).toEqual(JSON.stringify(METRIC_SCHEMA))
        expect(
            decoded.records.map((r) => [
                unwrap(r.metric_type),
                unwrap(r.value),
                unwrap(r.count),
                unwrap(r.series_fingerprint),
            ])
        ).toEqual([
            ['gauge', 3, 1n, FINGERPRINT],
            ['sum', 20, 2n, FINGERPRINT],
        ])
        expect(usageRows()).toEqual(
            expect.arrayContaining([
                [1, 'bytes_ingested', 300],
                [1, 'records_ingested', 3],
            ])
        )
    })

    it('passes a message through unchanged when it would decode past the chunk budget', async () => {
        const small = createMessage(teamA.api_token, 2)
        small.value = await encodeMetricRecords(METRIC_CONTAINER, [
            metricPoint('sum', 10, 1n),
            metricPoint('sum', 10, 2n),
        ])
        const large = createMessage(teamA.api_token, 3)
        large.value = await encodeMetricRecords(METRIC_CONTAINER, [
            metricPoint('sum', 10, 1n),
            metricPoint('sum', 10, 2n),
            metricPoint('sum', 10, 3n),
        ])
        const budget = (await decodeMetricRecords(small.value)).decodedBytes + 1
        const step = createAggregateMetricsStep<{
            message: Message
            teamId: number
            bytesUncompressed: number
            recordCount: number
        }>(() => true, budget)

        const results = await step(
            [small, large].map((message) => ({ message, teamId: teamA.id, bytesUncompressed: 1, recordCount: 1 }))
        )

        const values = results.map((result) =>
            result.type === PipelineResultType.OK ? result.value.message.value : null
        )
        expect((await decodeMetricRecords(values[0]!)).records.map((r) => unwrap(r.value))).toEqual([20])
        expect(values[1]).toBe(large.value)
    })
})
