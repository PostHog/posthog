import { mockProducer, mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { CODES, Message } from 'node-rdkafka'

import { KAFKA_APP_METRICS_2, KAFKA_LOGS_CLICKHOUSE, KAFKA_LOGS_INGESTION_DLQ } from '~/common/config/kafka-topics'
import { APP_METRICS_OUTPUT, AppMetricsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { DependencyUnavailableError } from '~/common/utils/db/error'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { createTeam, createTestTeamFixture, getTeam } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { getDefaultTracesIngestionConsumerConfig } from '../config'
import { LogRecord, encodeLogRecords } from '../log-record-avro'
import { DEFAULT_LOGS_RETENTION_DAYS, LogsIngestionConsumer, logMessageDlqCounter } from '../logs-ingestion-consumer'
import { LOGS_DLQ_OUTPUT, LOGS_OUTPUT, LogsDlqOutput, LogsOutput } from '../outputs/outputs'
import { DEFAULT_TRACES_RETENTION_DAYS } from '../retention/tracing-config-cache'
import { TracesIngestionConsumer } from '../traces-ingestion-consumer'
import { createLogsIngestionConsumer, createTracesIngestionConsumer } from './create-consumer'
import { LogsIngestionFrameworkConsumer } from './logs-ingestion-framework-consumer'
import { TracesIngestionFrameworkConsumer } from './traces-ingestion-framework-consumer'

const LibrdKafkaError = require('node-rdkafka/lib/error')
const { err2str } = require('node-rdkafka/librdkafka') as { err2str: (code: number) => string }

jest.setTimeout(5000)

jest.mock('~/common/utils/posthog', () => {
    const original = jest.requireActual('~/common/utils/posthog')
    return {
        ...original,
        captureException: jest.fn(),
    }
})

const avro = require('avsc')
const LOG_RECORD_TYPE = avro.Type.forSchema({
    type: 'record',
    name: 'LogRecord',
    fields: [
        { name: 'uuid', type: ['null', 'string'] },
        { name: 'trace_id', type: ['null', 'bytes'] },
        { name: 'span_id', type: ['null', 'bytes'] },
        { name: 'trace_flags', type: ['null', 'int'] },
        { name: 'timestamp', type: ['null', 'long'] },
        { name: 'observed_timestamp', type: ['null', 'long'] },
        { name: 'body', type: ['null', 'string'] },
        { name: 'severity_text', type: ['null', 'string'] },
        { name: 'severity_number', type: ['null', 'int'] },
        { name: 'service_name', type: ['null', 'string'] },
        { name: 'resource_attributes', type: ['null', { type: 'map', values: 'string' }] },
        { name: 'instrumentation_scope', type: ['null', 'string'] },
        { name: 'event_name', type: ['null', 'string'] },
        { name: 'attributes', type: ['null', { type: 'map', values: 'string' }] },
    ],
})

let offset = 0

async function createKafkaMessages(count: number, headers: Record<string, string>): Promise<Message[]> {
    return await Promise.all(
        Array.from({ length: count }, async () => {
            const record: LogRecord = {
                uuid: `test-uuid-${offset}`,
                trace_id: null,
                span_id: null,
                trace_flags: null,
                timestamp: Date.now() * 1000,
                observed_timestamp: Date.now() * 1000,
                body: 'Test log message',
                severity_text: 'info',
                severity_number: 9,
                service_name: 'test-service',
                resource_attributes: null,
                instrumentation_scope: null,
                event_name: null,
                attributes: null,
            }
            const value = await encodeLogRecords(LOG_RECORD_TYPE, 'zstandard', [record])
            return {
                key: null,
                value,
                size: value.length,
                topic: 'test',
                offset: offset++,
                timestamp: Date.now(),
                partition: 1,
                headers: Object.entries(headers).map(([key, header]) => ({ [key]: Buffer.from(header) })),
            }
        })
    )
}

function producedTo(topic: string): { headers?: Record<string, string>; value: unknown }[] {
    return mockProducerObserver
        .getProducedMessages()
        .filter((batch) => batch.topic === topic)
        .flatMap((batch) => batch.messages.map((message) => ({ headers: message.headers, value: message.value })))
}

const kafkaDeliveryError = (code: number): Error => LibrdKafkaError.create(new Error(err2str(code)))

function failLogsProduce(makeError: () => unknown, times = Infinity): () => void {
    const original = mockProducer.queueMessages
    const passthrough = original.bind(mockProducer)
    let failures = 0
    mockProducer.queueMessages = jest.fn().mockImplementation((topicMessages) => {
        const topic = Array.isArray(topicMessages) ? topicMessages[0]?.topic : topicMessages.topic
        if (topic === KAFKA_LOGS_CLICKHOUSE && failures++ < times) {
            throw makeError()
        }
        return passthrough(topicMessages)
    })
    return () => {
        mockProducer.queueMessages = original
    }
}

describe('LogsIngestionFrameworkConsumer', () => {
    let hub: Hub
    let team: Team
    let team2: Team
    let consumer: LogsIngestionFrameworkConsumer

    const consumerDeps = (): any => ({
        ...hub,
        outputs: new IngestionOutputs<AppMetricsOutput | LogsOutput | LogsDlqOutput>({
            [APP_METRICS_OUTPUT]: new SingleIngestionOutput(
                APP_METRICS_OUTPUT,
                KAFKA_APP_METRICS_2,
                mockProducer,
                'test'
            ),
            [LOGS_OUTPUT]: new SingleIngestionOutput(LOGS_OUTPUT, KAFKA_LOGS_CLICKHOUSE, mockProducer, 'test'),
            [LOGS_DLQ_OUTPUT]: new SingleIngestionOutput(
                LOGS_DLQ_OUTPUT,
                KAFKA_LOGS_INGESTION_DLQ,
                mockProducer,
                'test'
            ),
        }),
        usageBatch: new UsageRecordBatch(null, { unit: 'bytes', isTeamEnabled: () => false }),
        dependencyRetry: { retryCount: 2, initialRetryDelayMs: 1 },
    })

    const withoutKafka = <T extends { start(): Promise<void> }>(instance: T): T => {
        ;(instance as any)['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn().mockReturnValue({ status: 'healthy' }),
        }
        return instance
    }

    const tracesConfig = (overrides: Record<string, unknown> = {}): any => ({
        ...hub,
        ...getDefaultTracesIngestionConsumerConfig(),
        // A blank traces Redis host reuses the hub's Redis, so no second pool outlives the suite.
        TRACES_REDIS_HOST: '',
        ...overrides,
    })

    const processAndWait = async (messages: Message[]): Promise<void> => {
        await (
            await consumer.processKafkaBatch(messages)
        ).backgroundTask
    }

    beforeEach(async () => {
        jest.spyOn(Date, 'now').mockReturnValue(DateTime.fromISO('2025-01-01T00:00:00Z').toMillis())
        offset = 0
        hub = await createHub()
        team = (await createTestTeamFixture(hub.postgres)).team
        team2 = (await getTeam(hub.postgres, await createTeam(hub.postgres, team.organization_id)))!
        jest.spyOn(hub.quotaLimiting, 'isTeamTokenQuotaLimited').mockResolvedValue(false)
        consumer = withoutKafka(new LogsIngestionFrameworkConsumer(hub, consumerDeps()))
        await consumer.start()
    })

    afterEach(async () => {
        await consumer.stop()
        await closeHub(hub)
    })

    it('produces a valid message to the logs topic with the batch headers', async () => {
        const messages = await createKafkaMessages(1, { token: team.api_token })

        await processAndWait(messages)

        const produced = producedTo(KAFKA_LOGS_CLICKHOUSE)
        expect(produced).toHaveLength(1)
        expect(produced[0].headers).toEqual({
            token: team.api_token,
            team_id: team.id.toString(),
            'json-parse': 'false',
            'retention-days': DEFAULT_LOGS_RETENTION_DAYS.toString(),
            source_topic: messages[0].topic,
            source_partition: messages[0].partition.toString(),
        })
    })

    it('keeps the messages of overlapping batches apart', async () => {
        const first = await createKafkaMessages(2, { token: team.api_token })
        const second = await createKafkaMessages(1, { token: team2.api_token })

        const [a, b] = await Promise.all([consumer.processKafkaBatch(first), consumer.processKafkaBatch(second)])
        await Promise.all([a.backgroundTask, b.backgroundTask])

        expect(a.messages.map((m) => m.teamId)).toEqual([team.id, team.id])
        expect(b.messages.map((m) => m.teamId)).toEqual([team2.id])
        expect(producedTo(KAFKA_LOGS_CLICKHOUSE)).toHaveLength(3)
    })

    describe('logs produce errors', () => {
        it.each([
            ['a processing error', () => new Error('Producer error')],
            ['a Kafka error that a replay cannot fix', () => kafkaDeliveryError(CODES.ERRORS.ERR_INVALID_RECORD)],
        ])('sends the message to the DLQ on %s', async (_, makeError) => {
            const messages = await createKafkaMessages(1, { token: team.api_token })
            const dlqCounterSpy = jest.spyOn(logMessageDlqCounter, 'inc')
            const restore = failLogsProduce(makeError)

            try {
                await processAndWait(messages)
            } finally {
                restore()
            }

            expect(dlqCounterSpy).toHaveBeenCalledWith({ reason: 'Error', team_id: team.id.toString() })
            const dlq = producedTo(KAFKA_LOGS_INGESTION_DLQ)
            expect(dlq).toHaveLength(1)
            expect(dlq[0].headers).toMatchObject({
                source_topic: messages[0].topic,
                source_partition: messages[0].partition.toString(),
                source_offset: messages[0].offset.toString(),
            })
            expect(dlq[0].headers).toHaveProperty('error_message')
        })

        it('retries a dependency blip in place and produces the message once', async () => {
            const messages = await createKafkaMessages(1, { token: team.api_token })
            const restore = failLogsProduce(
                () => new DependencyUnavailableError('broker down', 'Kafka', new Error('broker down')),
                1
            )

            try {
                await processAndWait(messages)
            } finally {
                restore()
            }

            expect(producedTo(KAFKA_LOGS_CLICKHOUSE)).toHaveLength(1)
            expect(producedTo(KAFKA_LOGS_INGESTION_DLQ)).toHaveLength(0)
        })

        it.each([
            [
                'a dependency is unavailable',
                () => new DependencyUnavailableError('broker down', 'Kafka', new Error('broker down')),
            ],
            ['a delivery times out', () => kafkaDeliveryError(CODES.ERRORS.ERR__MSG_TIMED_OUT)],
            ['the producer queue is full', () => LibrdKafkaError.create(CODES.ERRORS.ERR__QUEUE_FULL)],
            ['the topic rejects authorization', () => kafkaDeliveryError(CODES.ERRORS.ERR_TOPIC_AUTHORIZATION_FAILED)],
        ])('fails the batch instead of DLQing when %s', async (_, makeError) => {
            const messages = await createKafkaMessages(1, { token: team.api_token })
            const restore = failLogsProduce(makeError)

            try {
                // Good data succeeds on redelivery, so quarantining it would lose it to an outage.
                await expect(processAndWait(messages)).rejects.toThrow()
            } finally {
                restore()
            }

            expect(producedTo(KAFKA_LOGS_INGESTION_DLQ)).toHaveLength(0)
        })

        it.each([
            ['the message fails to parse', { bytes_uncompressed: 'not-a-number' }],
            ['the message fails to process', {}],
        ])('fails only that batch when %s and the DLQ write fails', async (_, headers) => {
            // Two failing messages: the second failure must be awaited too, not left unhandled.
            const messages = await createKafkaMessages(2, { token: team.api_token, ...headers })
            const original = mockProducer.queueMessages
            mockProducer.queueMessages = jest.fn().mockRejectedValue(new Error('DLQ unavailable'))

            try {
                await expect(processAndWait(messages)).rejects.toThrow('DLQ unavailable')
            } finally {
                mockProducer.queueMessages = original
            }

            await processAndWait(await createKafkaMessages(1, { token: team.api_token }))
            expect(producedTo(KAFKA_LOGS_CLICKHOUSE)).toHaveLength(1)
        })
    })

    describe('TracesIngestionFrameworkConsumer', () => {
        it('reads the TRACES_ consumer and rate limiter config', () => {
            const traces = new TracesIngestionFrameworkConsumer(
                tracesConfig({
                    TRACES_INGESTION_CONSUMER_GROUP_ID: 'traces-group',
                    TRACES_INGESTION_CONSUMER_CONSUME_TOPIC: 'traces-topic',
                    TRACES_LIMITER_BUCKET_SIZE_KB: 42,
                }),
                consumerDeps()
            )

            expect(traces['groupId']).toBe('traces-group')
            expect(traces['topic']).toBe('traces-topic')
            expect(traces['rateLimiter']['config'].LOGS_LIMITER_BUCKET_SIZE_KB).toBe(42)
            expect(traces['rateLimiter']['rateLimiter'].getKeyPrefix()).toBe('@posthog-test/traces-rate-limiter/tokens')
            expect(traces.service.id).toBe('TracesIngestionConsumer')
        })

        it('takes its default retention from the tracing config, not logs_settings', async () => {
            const tracingConfigCache = { getRetentionDays: jest.fn().mockResolvedValue(90) }
            const traces = new TracesIngestionFrameworkConsumer(tracesConfig(), {
                ...consumerDeps(),
                tracingConfigCache,
            })
            const fallback = new TracesIngestionFrameworkConsumer(tracesConfig(), consumerDeps())

            expect(await traces['defaultRetentionDays'](team.id, { retention_days: 30 })).toBe(90)
            expect(tracingConfigCache.getRetentionDays).toHaveBeenCalledWith(team.id)
            expect(await fallback['defaultRetentionDays'](team.id, { retention_days: 30 })).toBe(
                DEFAULT_TRACES_RETENTION_DAYS
            )
        })
    })

    describe('the consumer factories the servers call', () => {
        it.each([
            [false, LogsIngestionConsumer],
            [true, LogsIngestionFrameworkConsumer],
        ])('builds the logs consumer for LOGS_INGESTION_USE_FRAMEWORK=%s', (useFramework, expected) => {
            const built = createLogsIngestionConsumer(
                { ...hub, LOGS_INGESTION_USE_FRAMEWORK: useFramework },
                consumerDeps()
            )

            expect(built.constructor).toBe(expected)
        })

        it.each([
            [false, TracesIngestionConsumer],
            [true, TracesIngestionFrameworkConsumer],
        ])('builds the traces consumer for TRACES_INGESTION_USE_FRAMEWORK=%s', (useFramework, expected) => {
            // The logs flag is set the other way, so the traces server must read its own flag.
            const built = createTracesIngestionConsumer(
                tracesConfig({
                    TRACES_INGESTION_USE_FRAMEWORK: useFramework,
                    LOGS_INGESTION_USE_FRAMEWORK: !useFramework,
                }),
                consumerDeps()
            )

            expect(built.constructor).toBe(expected)
        })
    })
})
