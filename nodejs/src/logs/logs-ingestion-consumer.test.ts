import { mockProducer, mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { compileHog } from '~/cdp/templates/compiler'
import { HogFunctionType } from '~/cdp/types'
import { KAFKA_APP_METRICS_2, KAFKA_LOGS_CLICKHOUSE, KAFKA_LOGS_INGESTION_DLQ } from '~/common/config/kafka-topics'
import { APP_METRICS_OUTPUT, AppMetricsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { getDefaultTracesIngestionConsumerConfig } from './config'
import { LogRecord, decodeLogRecords, encodeLogRecords } from './log-record-avro'
import {
    DEFAULT_LOGS_RETENTION_DAYS,
    LogsIngestionConsumer,
    type LogsIngestionConsumerDeps,
    logMessageDlqCounter,
    logMessageDroppedCounter,
    logsBillingBytesCreditedCounter,
    logsBytesAllowedCounter,
    logsBytesDroppedCounter,
    logsBytesReceivedCounter,
    logsRecordsAllowedCounter,
    logsRecordsBytesExceedPayloadCounter,
    logsRecordsDroppedCounter,
    logsRecordsReceivedCounter,
} from './logs-ingestion-consumer'
import { LOGS_DLQ_OUTPUT, LOGS_OUTPUT, LogsDlqOutput, LogsOutput } from './outputs/outputs'
import { compileRuleSet } from './sampling/compile-rules'
import type { SamplingRulesCache } from './sampling/sampling-rules-cache'
import { BASE_REDIS_KEY } from './services/logs-rate-limiter.service'
import { TracesIngestionConsumer } from './traces-ingestion-consumer'
import { LogsTransformerService } from './transformations/logs-transformer.service'

const DEFAULT_TEST_TIMEOUT = 5000
jest.setTimeout(DEFAULT_TEST_TIMEOUT)

jest.mock('~/common/utils/posthog', () => {
    const original = jest.requireActual('~/common/utils/posthog')
    return {
        ...original,
        captureException: jest.fn(),
    }
})

let offsetIncrementer = 0

const createKafkaMessage = async (logData: any, headers: Record<string, string> = {}): Promise<Message> => {
    // Create a LogRecord from the log data
    const record: LogRecord = {
        uuid: `test-uuid-${offsetIncrementer}`,
        trace_id: null,
        span_id: null,
        trace_flags: null,
        timestamp: DateTime.now().toMillis() * 1000, // microseconds
        observed_timestamp: DateTime.now().toMillis() * 1000,
        body: JSON.stringify(logData),
        severity_text: logData.level || 'info',
        severity_number: 9,
        service_name: logData.service || 'test-service',
        resource_attributes: null,
        instrumentation_scope: null,
        event_name: null,
        attributes: null,
    }

    // Encode as AVRO
    const avro = require('avsc')
    const logRecordType = avro.Type.forSchema({
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

    const value = await encodeLogRecords(logRecordType, 'zstandard', [record])

    return {
        key: null,
        value,
        size: value.length,
        topic: 'test',
        offset: offsetIncrementer++,
        timestamp: DateTime.now().toMillis(),
        partition: 1,
        headers: Object.entries(headers).map(([key, value]) => ({
            [key]: Buffer.from(value),
        })),
    }
}

const createKafkaMessages = async (logData: any[], headers: Record<string, string> = {}): Promise<Message[]> => {
    return Promise.all(logData.map((data) => createKafkaMessage(data, headers)))
}

// Single Kafka message carrying several log records, so a drop rule can remove some rows while
// others survive (partial drop) — the path that re-encodes and re-forwards to the output topic.
const createMultiRecordKafkaMessage = async (
    logDataList: any[],
    headers: Record<string, string> = {}
): Promise<Message> => {
    const avro = require('avsc')
    const logRecordType = avro.Type.forSchema({
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

    const records: LogRecord[] = logDataList.map((logData, i) => ({
        uuid: `test-uuid-${offsetIncrementer}-${i}`,
        trace_id: null,
        span_id: null,
        trace_flags: null,
        timestamp: DateTime.now().toMillis() * 1000,
        observed_timestamp: DateTime.now().toMillis() * 1000,
        body: JSON.stringify(logData),
        severity_text: logData.level || 'info',
        severity_number: 9,
        service_name: logData.service || 'test-service',
        resource_attributes: null,
        instrumentation_scope: null,
        event_name: null,
        attributes: null,
    }))

    const value = await encodeLogRecords(logRecordType, 'zstandard', records)

    return {
        key: null,
        value,
        size: value.length,
        topic: 'test',
        offset: offsetIncrementer++,
        timestamp: DateTime.now().toMillis(),
        partition: 1,
        headers: Object.entries(headers).map(([key, value]) => ({
            [key]: Buffer.from(value),
        })),
    }
}

describe('LogsIngestionConsumer', () => {
    let consumer: LogsIngestionConsumer
    let hub: Hub
    let team: Team
    let team2: Team
    let fixedTime: DateTime
    let logMessageDroppedCounterSpy: jest.SpyInstance

    const createLogsIngestionConsumer = async (
        hub: Hub,
        overrides: any = {},
        depsPartial: Partial<Pick<LogsIngestionConsumerDeps, 'samplingRulesCache' | 'logsTransformer'>> = {}
    ) => {
        const consumer = new LogsIngestionConsumer(
            hub,
            {
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
                ...depsPartial,
            },
            overrides
        )
        // NOTE: We don't actually use kafka so we skip instantiation for faster tests
        consumer['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn().mockReturnValue({ status: 'healthy' }),
        } as any
        await consumer.start()
        return consumer
    }

    const createLogMessage = (logData?: any): any => ({
        level: 'info',
        message: 'Test log message',
        timestamp: fixedTime.toISO()!,
        service: 'test-service',
        ...logData,
    })

    beforeEach(async () => {
        fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        jest.spyOn(Date.prototype, 'toISOString').mockReturnValue(fixedTime.toISO()!)

        offsetIncrementer = 0
        await resetTestDatabase()
        hub = await createHub()

        team = await getFirstTeam(hub.postgres)
        const team2Id = await createTeam(hub.postgres, team.organization_id)
        team2 = (await getTeam(hub.postgres, team2Id))!

        consumer = await createLogsIngestionConsumer(hub)

        await deleteKeysWithPrefix(consumer['redis'], BASE_REDIS_KEY)
        logMessageDroppedCounterSpy = jest.spyOn(logMessageDroppedCounter, 'inc')

        // Default to not quota limited - tests can override this
        jest.spyOn(hub.quotaLimiting, 'isTeamTokenQuotaLimited').mockResolvedValue(false)
    })

    afterEach(async () => {
        await consumer.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    const waitForBackgroundTasks = async (
        promise: Promise<{
            backgroundTask?: Promise<any>
        }>
    ) => {
        await (
            await promise
        ).backgroundTask
    }

    // Simple helper to transform getProducedMessages structure to match getProducedKafkaMessages
    const getProducedKafkaMessages = () => {
        const producedMessages = mockProducerObserver.getProducedMessages()
        const result = []

        for (const batch of producedMessages) {
            for (const message of batch.messages) {
                result.push({
                    topic: batch.topic,
                    key: message.key,
                    value: message.value || {},
                    headers: message.headers,
                })
            }
        }

        return result
    }

    describe('general', () => {
        it('should have the correct config', () => {
            expect(consumer['name']).toEqual('LogsIngestionConsumer')
            expect(consumer['groupId']).toEqual('ingestion-logs')
            expect(consumer['topic']).toEqual('logs_ingestion_test')
        })

        it('should allow config overrides', async () => {
            const overrides = {
                LOGS_INGESTION_CONSUMER_GROUP_ID: 'custom-group',
                LOGS_INGESTION_CONSUMER_CONSUME_TOPIC: 'custom-topic',
            }
            const customConsumer = await createLogsIngestionConsumer(hub, overrides)

            expect(customConsumer['groupId']).toBe('custom-group')
            expect(customConsumer['topic']).toBe('custom-topic')

            await customConsumer.stop()
        })

        it('should process a valid log message', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            expect(forSnapshot(getProducedKafkaMessages().map((m) => m.headers))).toMatchSnapshot()
        })

        it('should process multiple log messages', async () => {
            const logData = [
                createLogMessage({ level: 'info', message: 'First log' }),
                createLogMessage({ level: 'error', message: 'Second log' }),
                createLogMessage({ level: 'debug', message: 'Third log' }),
            ]
            const messages = await createKafkaMessages(logData, {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = getProducedKafkaMessages()
            expect(producedMessages).toHaveLength(3)
            expect(forSnapshot(producedMessages.map((m) => m.headers))).toMatchSnapshot()
        })
    })

    describe('message parsing and validation', () => {
        it('should drop messages with missing token', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                // missing token
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            expect(getProducedKafkaMessages()).toHaveLength(0)
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith({ reason: 'missing_token', team_id: 'unknown' })
        })

        it('should drop messages with invalid token', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: 'invalid-token',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            expect(getProducedKafkaMessages()).toHaveLength(0)
        })

        it('should preserve kafka message headers', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                myHeader: 'hello',
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = getProducedKafkaMessages()
            expect(forSnapshot(producedMessages.map((m) => m.headers))).toMatchSnapshot()
        })

        it('should overwrite existing headers', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
                team_id: '999',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))
            expect(forSnapshot(getProducedKafkaMessages().map((m) => m.headers))).toMatchSnapshot()
        })

        it('should handle parse errors gracefully', async () => {
            const messages = [
                {
                    key: null,
                    value: Buffer.from('invalid-json-is-fine-we-dont-check-for-errors'),
                    size: 1,
                    topic: 'test',
                    offset: offsetIncrementer++,
                    timestamp: DateTime.now().toMillis(),
                    partition: 1,
                    headers: [{ token: Buffer.from('missing') }],
                } as Message,
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            expect(getProducedKafkaMessages()).toHaveLength(0)
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith({ reason: 'team_not_found', team_id: 'unknown' })
        })

        it('should drop messages when team lookup fails and record unknown team_id', async () => {
            jest.spyOn(hub.teamManager, 'getTeamByToken').mockRejectedValueOnce(new Error('Database error'))

            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            expect(getProducedKafkaMessages()).toHaveLength(0)
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith({
                reason: 'team_lookup_error',
                team_id: 'unknown',
            })
        })
    })

    describe('batch processing', () => {
        it('should handle empty batch', async () => {
            const result = await consumer.processBatch([])

            expect(result.backgroundTask).toBeUndefined()
            expect(result.messages).toEqual([])
            await result.backgroundTask
        })

        it('should process batch with valid messages', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = getProducedKafkaMessages()
            expect(producedMessages).toHaveLength(1)
            expect(producedMessages[0].topic).toBe('clickhouse_logs_test')
            expect(producedMessages[0].headers).toEqual({
                token: team.api_token,
                team_id: team.id.toString(),
                'json-parse': 'false',
                'retention-days': DEFAULT_LOGS_RETENTION_DAYS.toString(),
            })
        })

        it('should produce messages with correct headers', async () => {
            const logData = createLogMessage({ level: 'error', message: 'Critical error' })
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = getProducedKafkaMessages()
            expect(producedMessages).toHaveLength(1)

            const message = producedMessages[0]
            expect(message.topic).toBe('clickhouse_logs_test')
            expect(message.key).toBeNull()
            expect(message.headers).toEqual({
                token: team.api_token,
                team_id: team.id.toString(),
                'json-parse': 'false',
                'retention-days': DEFAULT_LOGS_RETENTION_DAYS.toString(),
            })
        })

        it('should use custom logs_settings when set', async () => {
            // Update team with custom logs settings
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_team
                 SET logs_settings = $1
                 WHERE id = $2`,
                [JSON.stringify({ json_parse_logs: false, retention_days: 30 }), team.id],
                'updateTeamLogsSettings'
            )

            // Clear team cache to ensure fresh data
            hub.teamManager['lazyLoader'].markForRefresh(String(team.id))

            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = getProducedKafkaMessages()
            expect(producedMessages).toHaveLength(1)

            const message = producedMessages[0]
            expect(message.headers).toEqual({
                token: team.api_token,
                team_id: team.id.toString(),
                'json-parse': 'false',
                'retention-days': '30',
            })
        })
    })

    describe('service interface', () => {
        it('should provide correct service interface', () => {
            const service = consumer.service

            expect(service.id).toBe('LogsIngestionConsumer')
            expect(typeof service.onShutdown).toBe('function')
            expect(typeof service.healthcheck).toBe('function')
        })

        it('should return healthy status', () => {
            const healthCheck = consumer.isHealthy()

            expect(healthCheck).toEqual({ status: 'healthy' })
        })
    })

    describe('error handling', () => {
        it('should handle producer errors gracefully', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
            })

            // Mock producer's batched-write path to throw — this is what
            // SingleIngestionOutput.queueMessages drives under the hood.
            const originalQueueMessages = mockProducer.queueMessages
            const queueSpy = jest.fn().mockRejectedValue(new Error('Producer error'))
            mockProducer.queueMessages = queueSpy

            try {
                // Producer errors are caught and logged, not thrown
                await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

                // Verify the producer was called and would have failed
                expect(queueSpy).toHaveBeenCalled()
            } finally {
                mockProducer.queueMessages = originalQueueMessages
            }
        })

        it('should send failed messages to DLQ', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
            })

            const logMessageDlqCounterSpy = jest.spyOn(logMessageDlqCounter, 'inc')

            // Throw for the main logs topic but pass through to the real mock producer for the DLQ.
            const originalQueueMessages = mockProducer.queueMessages
            const passthrough = originalQueueMessages.bind(mockProducer)
            const queueSpy = jest.fn().mockImplementation((topicMessages) => {
                const t = Array.isArray(topicMessages) ? topicMessages[0]?.topic : topicMessages.topic
                if (t === 'clickhouse_logs_test') {
                    throw new Error('Producer error')
                }
                return passthrough(topicMessages)
            })
            mockProducer.queueMessages = queueSpy

            try {
                await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

                // Check that DLQ counter was incremented with team_id
                expect(logMessageDlqCounterSpy).toHaveBeenCalledWith({
                    reason: 'Error',
                    team_id: team.id.toString(),
                })

                // Check that a message was produced to the DLQ topic
                const dlqCalls = queueSpy.mock.calls.filter((call) => {
                    const t = Array.isArray(call[0]) ? call[0][0]?.topic : call[0].topic
                    return t === 'logs_ingestion_dlq_test'
                })
                expect(dlqCalls.length).toBeGreaterThan(0)

                // Verify DLQ message has error metadata in headers
                const dlqArg = dlqCalls[0][0]
                const dlqMessage = (Array.isArray(dlqArg) ? dlqArg[0] : dlqArg).messages[0]
                expect(dlqMessage.headers).toHaveProperty('error_message')
                expect(dlqMessage.headers).toHaveProperty('error_name')
                expect(dlqMessage.headers).toHaveProperty('failed_at')
            } finally {
                mockProducer.queueMessages = originalQueueMessages
            }
        })
    })

    describe('message routing', () => {
        it('should route messages to correct ClickHouse topic', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = getProducedKafkaMessages()
            expect(producedMessages).toHaveLength(1)
            expect(producedMessages[0].topic).toBe('clickhouse_logs_test')
        })

        it('should handle messages from different teams', async () => {
            const logData1 = createLogMessage({ message: 'Team 1 log' })
            const logData2 = createLogMessage({ message: 'Team 2 log' })

            const messages = [
                ...(await createKafkaMessages([logData1], {
                    token: team.api_token,
                })),
                ...(await createKafkaMessages([logData2], {
                    token: team2.api_token,
                })),
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = getProducedKafkaMessages()
            expect(producedMessages).toHaveLength(2)

            const team1Message = producedMessages.find((m) => m.headers?.team_id === team.id.toString())
            const team2Message = producedMessages.find((m) => m.headers?.team_id === team2.id.toString())

            expect(team1Message).toBeDefined()
            expect(team2Message).toBeDefined()
            expect(team1Message?.headers?.token).toBe(team.api_token)
            expect(team2Message?.headers?.token).toBe(team2.api_token)
        })
    })

    describe('message content preservation', () => {
        it('should preserve original message content', async () => {
            const logData = createLogMessage({
                level: 'warn',
                message: 'Warning message',
                timestamp: '2025-01-01T12:00:00.000Z',
                service: 'api-service',
                request_id: 'req-123',
                user_id: 'user-456',
            })

            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = getProducedKafkaMessages()
            expect(producedMessages).toHaveLength(1)

            expect(producedMessages[0].value).toEqual(messages[0].value)
        })

        it('should handle binary log data as we do not parse it', async () => {
            const binaryData = Buffer.from('binary log content')
            const messages = [
                {
                    key: null,
                    value: binaryData,
                    size: 1,
                    topic: 'test',
                    offset: offsetIncrementer++,
                    timestamp: DateTime.now().toMillis(),
                    partition: 1,
                    headers: [{ token: Buffer.from(team.api_token) }],
                } as Message,
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = mockProducerObserver.getProducedMessages()
            expect(producedMessages).toHaveLength(1)
            expect(producedMessages[0].messages[0].value).toEqual(binaryData)
        })
    })

    describe('rate limiting', () => {
        let bytesReceivedSpy: jest.SpyInstance
        let bytesAllowedSpy: jest.SpyInstance
        let bytesDroppedSpy: jest.SpyInstance
        let recordsReceivedSpy: jest.SpyInstance
        let recordsAllowedSpy: jest.SpyInstance
        let recordsDroppedSpy: jest.SpyInstance

        beforeEach(() => {
            bytesReceivedSpy = jest.spyOn(logsBytesReceivedCounter, 'inc')
            bytesAllowedSpy = jest.spyOn(logsBytesAllowedCounter, 'inc')
            bytesDroppedSpy = jest.spyOn(logsBytesDroppedCounter, 'inc')
            recordsReceivedSpy = jest.spyOn(logsRecordsReceivedCounter, 'inc')
            recordsAllowedSpy = jest.spyOn(logsRecordsAllowedCounter, 'inc')
            recordsDroppedSpy = jest.spyOn(logsRecordsDroppedCounter, 'inc')
        })

        it('should track metrics for messages', async () => {
            hub.LOGS_LIMITER_BUCKET_SIZE_KB = 2
            hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND = 1
            hub.LOGS_LIMITER_TTL_SECONDS = 3600

            await consumer.stop()
            consumer = await createLogsIngestionConsumer(hub)

            const logData1 = createLogMessage({ message: 'First' })
            const logData2 = createLogMessage({ message: 'Second' })

            const messages = [
                ...(await createKafkaMessages([logData1], {
                    token: team.api_token,
                    bytes_uncompressed: '1024',
                    bytes_compressed: '512',
                    record_count: '5',
                })),
                ...(await createKafkaMessages([logData2], {
                    token: team.api_token,
                    bytes_uncompressed: '2048',
                    bytes_compressed: '1024',
                    record_count: '10',
                })),
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            // Filter to only the logs topic (excludes app_metrics2 messages)
            const logsMessages = getProducedKafkaMessages().filter((m) => m.topic === 'clickhouse_logs_test')
            expect(logsMessages).toHaveLength(1)
            expect(bytesReceivedSpy).toHaveBeenCalledWith(3072)
            expect(bytesAllowedSpy).toHaveBeenCalledWith(1024)
            expect(bytesDroppedSpy).toHaveBeenCalledWith({ team_id: team.id.toString() }, 2048)
            expect(recordsReceivedSpy).toHaveBeenCalledWith(15)
            expect(recordsAllowedSpy).toHaveBeenCalledWith(5)
            expect(recordsDroppedSpy).toHaveBeenCalledWith({ team_id: team.id.toString() }, 10)
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith(
                { reason: 'rate_limited', team_id: team.id.toString() },
                1
            )
        })

        it('should handle missing header values with defaults', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            expect(getProducedKafkaMessages()).toHaveLength(1)
            expect(bytesReceivedSpy).toHaveBeenCalledWith(0)
            expect(recordsReceivedSpy).toHaveBeenCalledWith(0)
        })
    })

    describe('filterQuotaLimitedMessages', () => {
        it('should allow messages when not quota limited', async () => {
            jest.mocked(hub.quotaLimiting.isTeamTokenQuotaLimited).mockResolvedValue(false)

            const messages = await createKafkaMessages([createLogMessage()], {
                token: team.api_token,
                bytes_uncompressed: '1024',
                record_count: '5',
            })

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const { quotaAllowedMessages, quotaDroppedMessages } = await consumer['filterQuotaLimitedMessages'](parsed)

            expect(quotaAllowedMessages).toHaveLength(1)
            expect(quotaDroppedMessages).toHaveLength(0)
            expect(hub.quotaLimiting.isTeamTokenQuotaLimited).toHaveBeenCalledWith(team.api_token, 'logs_mb_ingested')
        })

        it('should drop messages when quota limited', async () => {
            jest.mocked(hub.quotaLimiting.isTeamTokenQuotaLimited).mockResolvedValue(true)

            const messages = await createKafkaMessages([createLogMessage()], {
                token: team.api_token,
                bytes_uncompressed: '1024',
                record_count: '5',
            })

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const { quotaAllowedMessages, quotaDroppedMessages } = await consumer['filterQuotaLimitedMessages'](parsed)

            expect(quotaAllowedMessages).toHaveLength(0)
            expect(quotaDroppedMessages).toHaveLength(1)
        })

        it('should check quota once per unique token', async () => {
            jest.mocked(hub.quotaLimiting.isTeamTokenQuotaLimited).mockResolvedValue(false)

            const messages = [
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '100',
                    record_count: '1',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '200',
                    record_count: '2',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team2.api_token,
                    bytes_uncompressed: '300',
                    record_count: '3',
                })),
            ]

            const parsed = await consumer['_parseKafkaBatch'](messages)
            await consumer['filterQuotaLimitedMessages'](parsed)

            // Should only call once per unique token, not once per message
            expect(hub.quotaLimiting.isTeamTokenQuotaLimited).toHaveBeenCalledTimes(2)
        })

        it('should handle mixed quota limited and non-limited teams', async () => {
            jest.mocked(hub.quotaLimiting.isTeamTokenQuotaLimited).mockImplementation((token) => {
                return Promise.resolve(token === team.api_token) // team1 is limited, team2 is not
            })

            const messages = [
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '100',
                    record_count: '1',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team2.api_token,
                    bytes_uncompressed: '200',
                    record_count: '2',
                })),
            ]

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const { quotaAllowedMessages, quotaDroppedMessages } = await consumer['filterQuotaLimitedMessages'](parsed)

            expect(quotaAllowedMessages).toHaveLength(1)
            expect(quotaAllowedMessages[0].token).toBe(team2.api_token)
            expect(quotaDroppedMessages).toHaveLength(1)
            expect(quotaDroppedMessages[0].token).toBe(team.api_token)
        })

        it('should increment dropped counter when quota limited', async () => {
            jest.mocked(hub.quotaLimiting.isTeamTokenQuotaLimited).mockResolvedValue(true)

            const messages = await createKafkaMessages([createLogMessage(), createLogMessage()], {
                token: team.api_token,
            })

            const parsed = await consumer['_parseKafkaBatch'](messages)
            await consumer['filterQuotaLimitedMessages'](parsed)

            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith(
                { reason: 'quota_limited', team_id: team.id.toString() },
                2
            )
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledTimes(1)
        })
    })

    describe('filterRateLimitedMessages', () => {
        it('should return allowed messages', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
                bytes_uncompressed: '1024',
                record_count: '5',
            })

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const { rateLimiterAllowedMessages, rateLimiterDroppedMessages } =
                await consumer['filterRateLimitedMessages'](parsed)

            expect(rateLimiterAllowedMessages).toHaveLength(1)
            expect(rateLimiterDroppedMessages).toHaveLength(0)
        })

        it('should track dropped messages when rate limited', async () => {
            hub.LOGS_LIMITER_BUCKET_SIZE_KB = 1 // 1024 bytes - allows first message
            hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND = 0.001
            hub.LOGS_LIMITER_TTL_SECONDS = 3600

            await consumer.stop()
            consumer = await createLogsIngestionConsumer(hub)

            const messages = [
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '512', // Fits in bucket
                    record_count: '1',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '2048', // Exceeds remaining bucket
                    record_count: '5',
                })),
            ]

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const { rateLimiterAllowedMessages, rateLimiterDroppedMessages } =
                await consumer['filterRateLimitedMessages'](parsed)

            expect(rateLimiterAllowedMessages).toHaveLength(1)
            expect(rateLimiterDroppedMessages).toHaveLength(1)
        })
    })

    describe('quota and rate limiting integration', () => {
        it('should apply quota limiting before rate limiting', async () => {
            // Team1 is quota limited, team2 is not
            jest.mocked(hub.quotaLimiting.isTeamTokenQuotaLimited).mockImplementation((token) => {
                return Promise.resolve(token === team.api_token)
            })

            const messages = [
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token, // quota limited - should be dropped before rate limiter
                    bytes_uncompressed: '100',
                    record_count: '1',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team2.api_token, // not quota limited - goes to rate limiter
                    bytes_uncompressed: '200',
                    record_count: '2',
                })),
            ]

            const result = await consumer.processKafkaBatch(messages)

            // Only team2's message should be allowed through
            expect(result.messages).toHaveLength(1)
            expect(result.messages[0].token).toBe(team2.api_token)

            // Verify quota_limited counter was incremented for team1
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith(
                { reason: 'quota_limited', team_id: team.id.toString() },
                1
            )
        })

        it('should drop messages from both quota and rate limiting', async () => {
            // Set up rate limit that allows first message but not second
            hub.LOGS_LIMITER_BUCKET_SIZE_KB = 1 // 1024 bytes
            hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND = 0.001
            hub.LOGS_LIMITER_TTL_SECONDS = 3600

            await consumer.stop()
            consumer = await createLogsIngestionConsumer(hub)

            // Team1 is quota limited
            jest.mocked(hub.quotaLimiting.isTeamTokenQuotaLimited).mockImplementation((token) => {
                return Promise.resolve(token === team.api_token)
            })

            const messages = [
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token, // quota limited
                    bytes_uncompressed: '100',
                    record_count: '1',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team2.api_token, // passes quota, fits in rate limit bucket
                    bytes_uncompressed: '500',
                    record_count: '1',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team2.api_token, // passes quota, but exceeds rate limit
                    bytes_uncompressed: '2000',
                    record_count: '2',
                })),
            ]

            const result = await consumer.processKafkaBatch(messages)

            // Only first team2 message should be allowed (quota ok + rate limit ok)
            expect(result.messages).toHaveLength(1)
            expect(result.messages[0].bytesUncompressed).toBe(500)

            // Verify both drop reasons were recorded
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith(
                { reason: 'quota_limited', team_id: team.id.toString() },
                1
            )
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith(
                { reason: 'rate_limited', team_id: team2.id.toString() },
                1
            )
        })

        it('should track usage stats correctly for mixed allowed and dropped messages', async () => {
            // Team1 is quota limited
            jest.mocked(hub.quotaLimiting.isTeamTokenQuotaLimited).mockImplementation((token) => {
                return Promise.resolve(token === team.api_token)
            })

            const messages = [
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token, // quota limited - dropped
                    bytes_uncompressed: '100',
                    record_count: '1',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team2.api_token, // allowed
                    bytes_uncompressed: '200',
                    record_count: '2',
                })),
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            // Check that app_metrics were emitted for both teams
            const appMetricsMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)

            // Team1 should have bytes_received and bytes_dropped
            const team1Metrics = appMetricsMessages.filter((m) => m.value.team_id === team.id)
            const team1BytesReceived = team1Metrics.find((m) => m.value.metric_name === 'bytes_received')
            const team1BytesDropped = team1Metrics.find((m) => m.value.metric_name === 'bytes_dropped')
            expect(team1BytesReceived?.value.count).toBe(100)
            expect(team1BytesDropped?.value.count).toBe(100)

            // Team2 should have bytes_received and bytes_ingested
            const team2Metrics = appMetricsMessages.filter((m) => m.value.team_id === team2.id)
            const team2BytesReceived = team2Metrics.find((m) => m.value.metric_name === 'bytes_received')
            const team2BytesIngested = team2Metrics.find((m) => m.value.metric_name === 'bytes_ingested')
            expect(team2BytesReceived?.value.count).toBe(200)
            expect(team2BytesIngested?.value.count).toBe(200)
        })

        it('should emit bytes_ingested_records from the bytes_uncompressed_records header', async () => {
            const messages = await createKafkaMessages([createLogMessage()], {
                token: team.api_token,
                bytes_uncompressed: '1024',
                bytes_uncompressed_records: '900',
                record_count: '5',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
            const bytesIngested = appMetricsMessages.find((m) => m.value.metric_name === 'bytes_ingested')
            const bytesIngestedRecords = appMetricsMessages.find(
                (m) => m.value.metric_name === 'bytes_ingested_records'
            )
            expect(bytesIngested?.value.count).toBe(1024)
            expect(bytesIngestedRecords?.value.count).toBe(900)
        })

        it('should flag and still emit when bytes_uncompressed_records exceeds bytes_uncompressed', async () => {
            const exceedCounterSpy = jest.spyOn(logsRecordsBytesExceedPayloadCounter, 'inc')
            const messages = await createKafkaMessages([createLogMessage()], {
                token: team.api_token,
                bytes_uncompressed: '1024',
                bytes_uncompressed_records: '1500',
                record_count: '5',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            expect(exceedCounterSpy).toHaveBeenCalledWith({ team_id: team.id.toString() })

            // The comparison metric is emitted as-is, even above the payload size —
            // it exists precisely to surface this case.
            const appMetricsMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
            const bytesIngested = appMetricsMessages.find((m) => m.value.metric_name === 'bytes_ingested')
            const bytesIngestedRecords = appMetricsMessages.find(
                (m) => m.value.metric_name === 'bytes_ingested_records'
            )
            expect(bytesIngested?.value.count).toBe(1024)
            expect(bytesIngestedRecords?.value.count).toBe(1500)
        })
    })

    describe('trackOutgoingTrafficAndBuildUsageStats', () => {
        it('should return usageStats with correct structure for allowed messages', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
                bytes_uncompressed: '1024',
                record_count: '5',
            })

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const usageStats = consumer['trackOutgoingTrafficAndBuildUsageStats'](parsed, [])

            const stats = usageStats.get(team.id)
            expect(stats).toBeDefined()
            expect(stats!.bytesReceived).toBe(1024)
            expect(stats!.recordsReceived).toBe(5)
            expect(stats!.bytesAllowed).toBe(1024)
            expect(stats!.recordsAllowed).toBe(5)
            expect(stats!.bytesDropped).toBe(0)
            expect(stats!.recordsDropped).toBe(0)
            expect(stats!.piiReplacements).toBe(0)
        })

        it('should sum bytesAllowedRecords and treat a missing header as zero', async () => {
            const messages = [
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '100',
                    bytes_uncompressed_records: '80',
                    record_count: '1',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '200',
                    record_count: '2',
                })),
            ]

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const usageStats = consumer['trackOutgoingTrafficAndBuildUsageStats'](parsed, [])

            const stats = usageStats.get(team.id)
            expect(stats!.bytesAllowed).toBe(300)
            expect(stats!.bytesAllowedRecords).toBe(80)
        })

        it('should aggregate stats for multiple messages from same team', async () => {
            const messages = [
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '100',
                    record_count: '1',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '200',
                    record_count: '2',
                })),
            ]

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const usageStats = consumer['trackOutgoingTrafficAndBuildUsageStats'](parsed, [])

            const stats = usageStats.get(team.id)
            expect(stats!.bytesReceived).toBe(300)
            expect(stats!.recordsReceived).toBe(3)
            expect(stats!.bytesAllowed).toBe(300)
            expect(stats!.recordsAllowed).toBe(3)
        })

        it('should track separate stats for different teams', async () => {
            const messages = [
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '100',
                    record_count: '1',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team2.api_token,
                    bytes_uncompressed: '200',
                    record_count: '2',
                })),
            ]

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const usageStats = consumer['trackOutgoingTrafficAndBuildUsageStats'](parsed, [])

            expect(usageStats.size).toBe(2)
            expect(usageStats.get(team.id)!.bytesAllowed).toBe(100)
            expect(usageStats.get(team2.id)!.bytesAllowed).toBe(200)
        })

        it('should track dropped stats correctly', async () => {
            // Set up rate limit that allows first message but not second
            hub.LOGS_LIMITER_BUCKET_SIZE_KB = 1 // 1024 bytes
            hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND = 0.001
            hub.LOGS_LIMITER_TTL_SECONDS = 3600

            await consumer.stop()
            consumer = await createLogsIngestionConsumer(hub)

            const messages = [
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '512', // Fits in bucket
                    record_count: '1',
                })),
                ...(await createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '2048', // Exceeds remaining bucket
                    record_count: '5',
                })),
            ]

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const { rateLimiterAllowedMessages, rateLimiterDroppedMessages } =
                await consumer['filterRateLimitedMessages'](parsed)
            const usageStats = consumer['trackOutgoingTrafficAndBuildUsageStats'](
                rateLimiterAllowedMessages,
                rateLimiterDroppedMessages
            )

            expect(usageStats.get(team.id)!.bytesAllowed).toBe(512)
            expect(usageStats.get(team.id)!.bytesDropped).toBe(2048)
        })
    })

    describe('queueUsageMetric', () => {
        const parseMetricValue = (value: any): any => {
            if (Buffer.isBuffer(value)) {
                return parseJSON(value.toString())
            }
            if (typeof value === 'string') {
                return parseJSON(value)
            }
            return value
        }

        it('should queue + flush metric with correct structure', async () => {
            consumer['queueUsageMetric'](123, 'test_metric', 500)
            await consumer['appMetricsAggregator'].flush()

            const messages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            expect(messages).toHaveLength(1)
            const value = parseMetricValue(messages[0].value)
            expect(value?.team_id).toBe(123)
            expect(value?.app_source).toBe('logs')
            expect(value?.app_source_id).toBe('')
            expect(value?.instance_id).toBe('')
            expect(value?.metric_kind).toBe('usage')
            expect(value?.metric_name).toBe('test_metric')
            expect(value?.count).toBe(500)
            // timestamp is now set at flush time, not by the caller
            expect(typeof value?.timestamp).toBe('string')
        })

        it('should not queue metric when count is zero', async () => {
            consumer['queueUsageMetric'](123, 'test_metric', 0)
            await consumer['appMetricsAggregator'].flush()

            const messages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            expect(messages).toHaveLength(0)
        })
    })

    describe('emitUsageMetrics', () => {
        const parseMetricValue = (value: any): any => {
            if (Buffer.isBuffer(value)) {
                return parseJSON(value.toString())
            }
            if (typeof value === 'string') {
                return parseJSON(value)
            }
            return value
        }
        it('should emit all metric types for each team', async () => {
            const usageStats = new Map([
                [
                    team.id,
                    {
                        bytesReceived: 1000,
                        recordsReceived: 10,
                        bytesAllowed: 800,
                        recordsAllowed: 8,
                        bytesAllowedRecords: 700,
                        bytesDropped: 200,
                        recordsDropped: 2,
                        piiReplacements: 0,
                        retentionDays: 30,
                    },
                ],
            ])

            await consumer['emitUsageMetrics'](usageStats)

            const messages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            expect(messages).toHaveLength(8)

            const metricNames = messages.map((m) => parseMetricValue(m.value)?.metric_name)
            expect(metricNames).toContain('bytes_received')
            expect(metricNames).toContain('records_received')
            expect(metricNames).toContain('bytes_ingested')
            expect(metricNames).toContain('bytes_ingested_records')
            expect(metricNames).toContain('records_ingested')
            expect(metricNames).toContain('bytes_dropped')
            expect(metricNames).toContain('records_dropped')
            expect(metricNames).toContain('bytes_ingested_retention_30d')
        })

        it.each([
            { retentionDays: 14, absent: ['bytes_ingested_retention_30d', 'bytes_ingested_retention_90d'] },
            { retentionDays: 30, absent: ['bytes_ingested_retention_14d', 'bytes_ingested_retention_90d'] },
            { retentionDays: 90, absent: ['bytes_ingested_retention_14d', 'bytes_ingested_retention_30d'] },
        ])(
            'should emit only bytes_ingested_retention_${retentionDays}d for the matching tier',
            async ({ retentionDays, absent }) => {
                const usageStats = new Map([
                    [
                        team.id,
                        {
                            bytesReceived: 500,
                            recordsReceived: 5,
                            bytesAllowed: 500,
                            recordsAllowed: 5,
                            bytesAllowedRecords: 0,
                            bytesDropped: 0,
                            recordsDropped: 0,
                            piiReplacements: 0,
                            retentionDays,
                        },
                    ],
                ])

                await consumer['emitUsageMetrics'](usageStats)

                const messages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)
                const retentionMetric = messages
                    .map((m) => parseMetricValue(m.value))
                    .find((m) => m?.metric_name === `bytes_ingested_retention_${retentionDays}d`)

                expect(retentionMetric?.count).toBe(500)
                const metricNames = messages.map((m) => parseMetricValue(m.value)?.metric_name)
                for (const name of absent) {
                    expect(metricNames).not.toContain(name)
                }
            }
        )

        it('should skip zero-count metrics', async () => {
            const usageStats = new Map([
                [
                    team.id,
                    {
                        bytesReceived: 1000,
                        recordsReceived: 10,
                        bytesAllowed: 1000,
                        recordsAllowed: 10,
                        bytesAllowedRecords: 0,
                        bytesDropped: 0,
                        recordsDropped: 0,
                        piiReplacements: 0,
                        retentionDays: 14,
                    },
                ],
            ])

            await consumer['emitUsageMetrics'](usageStats)

            const messages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            // 4 non-zero base metrics (no dropped) + 1 retention tier row
            expect(messages).toHaveLength(5)
            const metricNames = messages.map((m) => parseMetricValue(m.value)?.metric_name)
            expect(metricNames).not.toContain('bytes_dropped')
            expect(metricNames).not.toContain('records_dropped')
            expect(metricNames).toContain('bytes_ingested_retention_14d')
        })

        it('should handle empty usageStats', async () => {
            const usageStats = new Map()

            await consumer['emitUsageMetrics'](usageStats)

            const messages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            expect(messages).toHaveLength(0)
        })

        it('should emit metrics for multiple teams', async () => {
            const usageStats = new Map([
                [
                    team.id,
                    {
                        bytesReceived: 100,
                        recordsReceived: 1,
                        bytesAllowed: 100,
                        recordsAllowed: 1,
                        bytesAllowedRecords: 0,
                        bytesDropped: 0,
                        recordsDropped: 0,
                        piiReplacements: 0,
                        retentionDays: 30,
                    },
                ],
                [
                    team2.id,
                    {
                        bytesReceived: 200,
                        recordsReceived: 2,
                        bytesAllowed: 200,
                        recordsAllowed: 2,
                        bytesAllowedRecords: 0,
                        bytesDropped: 0,
                        recordsDropped: 0,
                        piiReplacements: 0,
                        retentionDays: 90,
                    },
                ],
            ])

            await consumer['emitUsageMetrics'](usageStats)

            const messages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            // 4 base metrics + 1 retention tier per team (no dropped) = 10 total
            expect(messages).toHaveLength(10)

            const team1Messages = messages.filter((m) => parseMetricValue(m.value)?.team_id === team.id)
            const team2Messages = messages.filter((m) => parseMetricValue(m.value)?.team_id === team2.id)
            expect(team1Messages).toHaveLength(5)
            expect(team2Messages).toHaveLength(5)
        })
    })

    describe('app metrics emission (integration)', () => {
        const parseMetricValue = (value: any): any => {
            if (Buffer.isBuffer(value)) {
                return parseJSON(value.toString())
            }
            if (typeof value === 'string') {
                return parseJSON(value)
            }
            return value
        }

        it('should emit usage metrics to app_metrics2 topic', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
                bytes_uncompressed: '1024',
                record_count: '5',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            expect(appMetricsMessages.length).toBeGreaterThan(0)

            const metricNames = appMetricsMessages.map((m) => {
                const value = parseMetricValue(m.value)
                return value.metric_name
            })

            expect(metricNames).toContain('bytes_received')
            expect(metricNames).toContain('records_received')
            expect(metricNames).toContain('bytes_ingested')
            expect(metricNames).toContain('records_ingested')
        })

        it('should emit pii_replacements when pii scrub is on and the body has pattern matches', async () => {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_team
                 SET logs_settings = $1
                 WHERE id = $2`,
                [JSON.stringify({ pii_scrub_logs: true, json_parse_logs: false }), team.id],
                'updateTeamLogsPiiScrub'
            )
            hub.teamManager['lazyLoader'].markForRefresh(String(team.id))

            const logData = createLogMessage({ message: 'email me at foo@bar.com' })
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
                bytes_uncompressed: '200',
                record_count: '1',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)
            const pii = appMetricsMessages.find((m) => {
                const value = parseMetricValue(m.value)
                return value.metric_name === 'pii_replacements' && value.team_id === team.id
            })
            expect(pii).toBeDefined()
            expect(parseMetricValue(pii!.value).count).toBe(1)
        })

        it('should emit correct metric values per team', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
                bytes_uncompressed: '2048',
                record_count: '10',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            const bytesIngestedMetric = appMetricsMessages.find((m) => {
                const value = parseMetricValue(m.value)
                return value.metric_name === 'bytes_ingested'
            })

            expect(bytesIngestedMetric).toBeDefined()
            const value = parseMetricValue(bytesIngestedMetric!.value)
            expect(value.team_id).toBe(team.id)
            expect(value.app_source).toBe('logs')
            expect(value.metric_kind).toBe('usage')
            expect(value.count).toBe(2048)
        })

        it('should emit dropped metrics when rate limited', async () => {
            hub.LOGS_LIMITER_BUCKET_SIZE_KB = 1
            hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND = 0.001
            hub.LOGS_LIMITER_TTL_SECONDS = 3600

            await consumer.stop()
            consumer = await createLogsIngestionConsumer(hub)

            const logData1 = createLogMessage({ message: 'First' })
            const logData2 = createLogMessage({ message: 'Second - will be dropped' })

            const messages = [
                ...(await createKafkaMessages([logData1], {
                    token: team.api_token,
                    bytes_uncompressed: '512',
                    record_count: '2',
                })),
                ...(await createKafkaMessages([logData2], {
                    token: team.api_token,
                    bytes_uncompressed: '2048',
                    record_count: '8',
                })),
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            const bytesDroppedMetric = appMetricsMessages.find((m) => {
                const value = parseMetricValue(m.value)
                return value.metric_name === 'bytes_dropped'
            })

            expect(bytesDroppedMetric).toBeDefined()
            const value = parseMetricValue(bytesDroppedMetric!.value)
            expect(value.count).toBe(2048)
        })

        it('should aggregate metrics across multiple messages from same team', async () => {
            const logData1 = createLogMessage({ message: 'First' })
            const logData2 = createLogMessage({ message: 'Second' })

            const messages = [
                ...(await createKafkaMessages([logData1], {
                    token: team.api_token,
                    bytes_uncompressed: '100',
                    record_count: '1',
                })),
                ...(await createKafkaMessages([logData2], {
                    token: team.api_token,
                    bytes_uncompressed: '200',
                    record_count: '2',
                })),
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            const bytesIngestedMetric = appMetricsMessages.find((m) => {
                const value = parseMetricValue(m.value)
                return value.metric_name === 'bytes_ingested' && value.team_id === team.id
            })

            expect(bytesIngestedMetric).toBeDefined()
            const value = parseMetricValue(bytesIngestedMetric!.value)
            expect(value.count).toBe(300) // 100 + 200
        })

        it('should emit separate metrics for different teams', async () => {
            const logData1 = createLogMessage({ message: 'Team 1' })
            const logData2 = createLogMessage({ message: 'Team 2' })

            const messages = [
                ...(await createKafkaMessages([logData1], {
                    token: team.api_token,
                    bytes_uncompressed: '100',
                    record_count: '1',
                })),
                ...(await createKafkaMessages([logData2], {
                    token: team2.api_token,
                    bytes_uncompressed: '200',
                    record_count: '2',
                })),
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            const team1Metrics = appMetricsMessages.filter((m) => {
                const value = parseMetricValue(m.value)
                return value.team_id === team.id && value.metric_name === 'bytes_ingested'
            })

            const team2Metrics = appMetricsMessages.filter((m) => {
                const value = parseMetricValue(m.value)
                return value.team_id === team2.id && value.metric_name === 'bytes_ingested'
            })

            expect(team1Metrics).toHaveLength(1)
            expect(team2Metrics).toHaveLength(1)
            expect(parseMetricValue(team1Metrics[0].value).count).toBe(100)
            expect(parseMetricValue(team2Metrics[0].value).count).toBe(200)
        })

        it('should not emit metrics with zero count', async () => {
            const logData = createLogMessage()
            const messages = await createKafkaMessages([logData], {
                token: team.api_token,
                bytes_uncompressed: '100',
                record_count: '1',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)

            // Should not have drop metrics since nothing was dropped or sampled out
            const droppedMetrics = appMetricsMessages.filter((m) => {
                const value = parseMetricValue(m.value)
                return (
                    value.metric_name === 'bytes_dropped' ||
                    value.metric_name === 'records_dropped' ||
                    value.metric_name === 'sampling_records_dropped_by_rule'
                )
            })

            expect(droppedMetrics).toHaveLength(0)
        })

        describe('sampling usage to app_metrics2', () => {
            let mockSamplingCache: Pick<SamplingRulesCache, 'getCompiledRuleSet'>

            beforeEach(async () => {
                await consumer.stop()
                mockSamplingCache = {
                    getCompiledRuleSet: (teamId: number) =>
                        Promise.resolve(
                            teamId === team.id
                                ? compileRuleSet([
                                      {
                                          id: '00000000-0000-0000-0000-0000000000aa',
                                          rule_type: 'severity_sampling',
                                          scope_service: 'test-service',
                                          scope_path_pattern: null,
                                          scope_attribute_filters: [],
                                          config: { actions: { INFO: { type: 'drop' } } },
                                      },
                                  ])
                                : compileRuleSet([])
                        ),
                }
                consumer = await createLogsIngestionConsumer(
                    hub,
                    {},
                    { samplingRulesCache: mockSamplingCache as SamplingRulesCache }
                )
                await deleteKeysWithPrefix(consumer['redis'], BASE_REDIS_KEY)
            })

            it('should emit sampling_records_dropped_by_rule when head sampling drops log lines', async () => {
                const logData = createLogMessage({ level: 'info' })
                const messages = await createKafkaMessages([logData], {
                    token: team.api_token,
                    bytes_uncompressed: '400',
                    record_count: '1',
                })

                await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

                const appMetricsMessages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)
                expect(
                    appMetricsMessages.some((m) => parseMetricValue(m.value).metric_name === 'sampling_records_dropped')
                ).toBe(false)

                const byRule = appMetricsMessages.find((m) => {
                    const value = parseMetricValue(m.value)
                    return (
                        value.metric_name === 'sampling_records_dropped_by_rule' &&
                        value.team_id === team.id &&
                        value.instance_id === '00000000-0000-0000-0000-0000000000aa'
                    )
                })
                expect(byRule).toBeDefined()
                expect(parseMetricValue(byRule!.value).count).toBe(1)
            })

            const sendDroppedAndKeptMessages = async () => {
                // Two single-record messages: the info one is fully dropped by the rule
                // (credit = its whole 400-byte header), the error one is kept (600 bytes).
                const messages = [
                    ...(await createKafkaMessages([createLogMessage({ level: 'info' })], {
                        token: team.api_token,
                        bytes_uncompressed: '400',
                        record_count: '1',
                    })),
                    ...(await createKafkaMessages([createLogMessage({ level: 'error' })], {
                        token: team.api_token,
                        bytes_uncompressed: '600',
                        record_count: '1',
                    })),
                ]
                await waitForBackgroundTasks(consumer.processKafkaBatch(messages))
            }

            const teamBytesIngested = (): number | undefined => {
                const m = getProducedKafkaMessages()
                    .filter((m) => m.topic === KAFKA_APP_METRICS_2)
                    .find((m) => {
                        const value = parseMetricValue(m.value)
                        return value.metric_name === 'bytes_ingested' && value.team_id === team.id
                    })
                return m ? parseMetricValue(m.value).count : undefined
            }

            it('shadow mode (default): computes the drop credit but bills the full gross bytes', async () => {
                const creditSpy = jest.spyOn(logsBillingBytesCreditedCounter, 'inc')

                await sendDroppedAndKeptMessages()

                // The would-be credit is computed and observable...
                expect(creditSpy).toHaveBeenCalledWith({ team_id: team.id.toString() }, 400)
                // ...but billed usage is untouched: full gross of both messages.
                expect(teamBytesIngested()).toBe(1000)
            })

            it('credits dropped rows off bytes_ingested when LOGS_BILLING_PRORATE_ENABLED', async () => {
                await consumer.stop()
                consumer = await createLogsIngestionConsumer(
                    hub,
                    { LOGS_BILLING_PRORATE_ENABLED: true },
                    { samplingRulesCache: mockSamplingCache as SamplingRulesCache }
                )
                await deleteKeysWithPrefix(consumer['redis'], BASE_REDIS_KEY)

                await sendDroppedAndKeptMessages()

                // The fully-dropped message's 400-byte header is credited; only the kept one bills.
                expect(teamBytesIngested()).toBe(600)
            })

            const outputHeaders = (): Record<string, string> | undefined =>
                getProducedKafkaMessages().find((m) => m.topic === KAFKA_LOGS_CLICKHOUSE)?.headers as
                    | Record<string, string>
                    | undefined

            // One message, two equal-content records: the info row is dropped, the error row survives.
            // Shadow mode forwards the original gross headers; enabled mode scales both by the same
            // dropped content fraction (~0.5), so the 500/1000 ratio is preserved.
            it.each([
                { label: 'shadow mode (default) forwards the original gross size headers', enabled: false },
                { label: 'enabled mode pro-rates the forwarded size headers by the dropped fraction', enabled: true },
            ])('$label', async ({ enabled }) => {
                if (enabled) {
                    await consumer.stop()
                    consumer = await createLogsIngestionConsumer(
                        hub,
                        { LOGS_BILLING_PRORATE_ENABLED: true },
                        { samplingRulesCache: mockSamplingCache as SamplingRulesCache }
                    )
                    await deleteKeysWithPrefix(consumer['redis'], BASE_REDIS_KEY)
                }

                const message = await createMultiRecordKafkaMessage(
                    [createLogMessage({ level: 'info' }), createLogMessage({ level: 'error' })],
                    { token: team.api_token, bytes_uncompressed: '1000', bytes_compressed: '500', record_count: '2' }
                )
                await waitForBackgroundTasks(consumer.processKafkaBatch([message]))

                const uncompressed = parseInt(outputHeaders()!.bytes_uncompressed, 10)
                const compressed = parseInt(outputHeaders()!.bytes_compressed, 10)
                const recordCount = parseInt(outputHeaders()!.record_count, 10)
                if (!enabled) {
                    expect(uncompressed).toBe(1000)
                    expect(compressed).toBe(500)
                    expect(recordCount).toBe(2)
                    return
                }
                expect(uncompressed).toBeGreaterThan(0)
                expect(uncompressed).toBeLessThan(1000)
                expect(compressed).toBeGreaterThan(0)
                expect(compressed).toBeLessThan(500)
                expect(compressed / uncompressed).toBeCloseTo(0.5, 5)
                // The dropped info row is removed from the count exactly; only the error row survives.
                expect(recordCount).toBe(1)
            })
        })
    })

    describe('thread relief', () => {
        jest.setTimeout(30000)

        beforeEach(async () => {
            // Parent beforeEach mocks Date.now/toISOString — restore for real-time tracking.
            jest.spyOn(Date, 'now').mockRestore()
            jest.spyOn(Date.prototype, 'toISOString').mockRestore()

            // Enable PII scrub + JSON parse so processLogMessageBuffer does real CPU work
            // (without these settings it short-circuits and never decodes the buffer).
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_team SET logs_settings = $1 WHERE id = $2`,
                [JSON.stringify({ pii_scrub_logs: true, json_parse_logs: true }), team.id],
                'updateTeamLogsForThreadRelief'
            )
            hub.teamManager['lazyLoader'].markForRefresh(String(team.id))
        })

        it('should process large batches without blocking the main thread', async () => {
            // Body large enough that JSON parse + PII scrub do meaningful sync work per message.
            const body = JSON.stringify({
                user_id: 'usr_abc123',
                email: 'jane.doe@example.com',
                nested: { a: 1, b: 'two', c: [1, 2, 3, 4, 5] },
                message: 'A long log message ' + 'x'.repeat(500),
            })

            const numberToTest = 2000
            const messages = await createKafkaMessages(
                Array.from({ length: numberToTest }, () => ({ message: body })),
                { token: team.api_token }
            )

            // Track event-loop lag only during the consumer's processing.
            let lastCheck = Date.now()
            let longestDelay = 0
            const interval = setInterval(() => {
                longestDelay = Math.max(longestDelay, Date.now() - lastCheck)
                lastCheck = Date.now()
            }, 0)

            try {
                await waitForBackgroundTasks(consumer.processKafkaBatch(messages))
            } finally {
                clearInterval(interval)
            }

            const logsMessages = getProducedKafkaMessages().filter((m) => m.topic === 'clickhouse_logs_test')
            expect(logsMessages).toHaveLength(numberToTest)

            console.log(`[thread-relief] longestDelay = ${longestDelay}ms`)
            expect(longestDelay).toBeLessThan(120)
        })
    })

    describe('TracesIngestionConsumer billing identity', () => {
        const createTracesIngestionConsumer = (configOverrides: Record<string, any> = {}): TracesIngestionConsumer => {
            const tracesConsumer = new TracesIngestionConsumer(
                // Blank the traces Redis host so it reuses the hub's pool (like the logs-consumer tests),
                // avoiding a second eager pool that would keep handles open after the suite.
                { ...hub, ...getDefaultTracesIngestionConsumerConfig(), TRACES_REDIS_HOST: '', ...configOverrides },
                {
                    ...hub,
                    outputs: new IngestionOutputs<AppMetricsOutput | LogsOutput | LogsDlqOutput>({
                        [APP_METRICS_OUTPUT]: new SingleIngestionOutput(
                            APP_METRICS_OUTPUT,
                            KAFKA_APP_METRICS_2,
                            mockProducer,
                            'test'
                        ),
                        [LOGS_OUTPUT]: new SingleIngestionOutput(
                            LOGS_OUTPUT,
                            KAFKA_LOGS_CLICKHOUSE,
                            mockProducer,
                            'test'
                        ),
                        [LOGS_DLQ_OUTPUT]: new SingleIngestionOutput(
                            LOGS_DLQ_OUTPUT,
                            KAFKA_LOGS_INGESTION_DLQ,
                            mockProducer,
                            'test'
                        ),
                    }),
                }
            )
            tracesConsumer['kafkaConsumer'] = {
                connect: jest.fn(),
                disconnect: jest.fn(),
                isHealthy: jest.fn().mockReturnValue({ status: 'healthy' }),
            } as any
            return tracesConsumer
        }

        it('meters usage as traces, not logs', async () => {
            const tracesConsumer = createTracesIngestionConsumer()
            tracesConsumer['queueUsageMetric'](team.id, 'bytes_ingested', 500)
            await tracesConsumer['appMetricsAggregator'].flush()

            const messages = getProducedKafkaMessages().filter((m) => m.topic === KAFKA_APP_METRICS_2)
            expect(messages).toHaveLength(1)
            const value = Buffer.isBuffer(messages[0].value)
                ? parseJSON(messages[0].value.toString())
                : parseJSON(messages[0].value as string)
            expect(value?.app_source).toBe('traces')
        })

        it('quota-limits against traces_mb_ingested, not logs_mb_ingested', async () => {
            jest.mocked(hub.quotaLimiting.isTeamTokenQuotaLimited).mockResolvedValue(false)
            const tracesConsumer = createTracesIngestionConsumer()

            const messages = await createKafkaMessages([createLogMessage()], {
                token: team.api_token,
                bytes_uncompressed: '1024',
                record_count: '5',
            })
            const parsed = await tracesConsumer['_parseKafkaBatch'](messages)
            await tracesConsumer['filterQuotaLimitedMessages'](parsed)

            expect(hub.quotaLimiting.isTeamTokenQuotaLimited).toHaveBeenCalledWith(team.api_token, 'traces_mb_ingested')
        })

        it('rate-limits against its own Redis key namespace, not the logs one', () => {
            const tracesConsumer = createTracesIngestionConsumer()
            const prefix = tracesConsumer['rateLimiter']['rateLimiter'].getKeyPrefix()

            expect(prefix).toBe('@posthog-test/traces-rate-limiter/tokens')
            expect(prefix).not.toContain('logs-rate-limiter')
        })

        it('applies TRACES_LIMITER_* tuning rather than the logs limiter config', () => {
            const tracesConsumer = createTracesIngestionConsumer({
                TRACES_LIMITER_BUCKET_SIZE_KB: 42,
                TRACES_LIMITER_REFILL_RATE_KB_PER_SECOND: 7,
            })
            const limiterConfig = tracesConsumer['rateLimiter']['config']

            expect(limiterConfig.LOGS_LIMITER_BUCKET_SIZE_KB).toBe(42)
            expect(limiterConfig.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND).toBe(7)
        })
    })

    describe('hog log transformations', () => {
        let transformerConsumer: LogsIngestionConsumer

        const buildTransformer = async (hog: string): Promise<LogsTransformerService> => {
            const fn = {
                id: '00000000-0000-0000-0000-000000000001',
                team_id: team.id,
                name: 'Test log transformation',
                type: 'transformation_log',
                enabled: true,
                bytecode: await compileHog(hog),
                inputs: {},
                encrypted_inputs: null,
                execution_order: 1,
                created_at: new Date().toISOString(),
            } as unknown as HogFunctionType
            const manager = {
                getHogFunctionsForTeams: jest.fn().mockResolvedValue({ [team.id]: [fn] }),
                getHogFunctionIdsForTeams: jest.fn().mockResolvedValue({ [team.id]: [fn.id] }),
            }
            const monitoring = { queueAppMetric: jest.fn(), queueLogs: jest.fn(), flush: jest.fn() }
            return new LogsTransformerService(manager as any, monitoring as any, {
                siteUrl: 'http://localhost:8010',
                hogTimeoutMs: 10,
                messageBudgetMs: 100,
                batchBudgetMs: 2000,
                maxErrorLogsPerFunctionPerMessage: 3,
                hogWatcherSampleRate: 0,
            })
        }

        afterEach(async () => {
            await transformerConsumer?.stop()
        })

        it('applies an enabled transformation to produced records', async () => {
            const logsTransformer = await buildTransformer(`
                let rec := record
                rec.body := replaceAll(rec.body, 'sensitive', '[REDACTED]')
                return rec
            `)
            transformerConsumer = await createLogsIngestionConsumer(
                hub,
                { LOGS_TRANSFORMATIONS_ENABLED_TEAMS: '*' },
                { logsTransformer }
            )

            const messages = await createKafkaMessages([createLogMessage({ message: 'something sensitive here' })], {
                token: team.api_token,
            })
            await waitForBackgroundTasks(transformerConsumer.processKafkaBatch(messages))

            const logsMessages = getProducedKafkaMessages().filter((m) => m.topic === 'clickhouse_logs_test')
            expect(logsMessages).toHaveLength(1)
            const [, , records] = await decodeLogRecords(logsMessages[0].value as Buffer)
            expect(records).toHaveLength(1)
            expect(records[0].body).toContain('[REDACTED]')
            expect(records[0].body).not.toContain('sensitive')
        })

        it('does not produce a message when transformations drop every record', async () => {
            const logsTransformer = await buildTransformer(`return null`)
            transformerConsumer = await createLogsIngestionConsumer(
                hub,
                { LOGS_TRANSFORMATIONS_ENABLED_TEAMS: '*' },
                { logsTransformer }
            )

            const messages = await createKafkaMessages([createLogMessage()], { token: team.api_token })
            await waitForBackgroundTasks(transformerConsumer.processKafkaBatch(messages))

            const logsMessages = getProducedKafkaMessages().filter((m) => m.topic === 'clickhouse_logs_test')
            expect(logsMessages).toHaveLength(0)
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith(
                { reason: 'transformations_all_dropped', team_id: team.id.toString() },
                1
            )
        })

        it('attributes the full-message drop to transformations when sampling kept survivors', async () => {
            const logsTransformer = await buildTransformer(`return null`)
            // Drop rule that does not match the record, so sampling keeps it and the
            // transformation is what removes the last survivor.
            const mockSamplingCache: Pick<SamplingRulesCache, 'getCompiledRuleSet'> = {
                getCompiledRuleSet: () =>
                    Promise.resolve(
                        compileRuleSet([
                            {
                                id: '00000000-0000-0000-0000-0000000000ab',
                                rule_type: 'severity_sampling',
                                scope_service: 'test-service',
                                scope_path_pattern: null,
                                scope_attribute_filters: [],
                                config: { actions: { INFO: { type: 'drop' } } },
                            },
                        ])
                    ),
            }
            transformerConsumer = await createLogsIngestionConsumer(
                hub,
                { LOGS_TRANSFORMATIONS_ENABLED_TEAMS: '*' },
                { logsTransformer, samplingRulesCache: mockSamplingCache as SamplingRulesCache }
            )

            const messages = await createKafkaMessages([createLogMessage({ level: 'error' })], {
                token: team.api_token,
            })
            await waitForBackgroundTasks(transformerConsumer.processKafkaBatch(messages))

            const logsMessages = getProducedKafkaMessages().filter((m) => m.topic === 'clickhouse_logs_test')
            expect(logsMessages).toHaveLength(0)
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith(
                { reason: 'transformations_all_dropped', team_id: team.id.toString() },
                1
            )
        })

        it('does not run transformations when the team is not in the allowlist', async () => {
            const logsTransformer = await buildTransformer(`return null`)
            transformerConsumer = await createLogsIngestionConsumer(
                hub,
                { LOGS_TRANSFORMATIONS_ENABLED_TEAMS: '' },
                { logsTransformer }
            )

            const messages = await createKafkaMessages([createLogMessage()], { token: team.api_token })
            await waitForBackgroundTasks(transformerConsumer.processKafkaBatch(messages))

            const logsMessages = getProducedKafkaMessages().filter((m) => m.topic === 'clickhouse_logs_test')
            expect(logsMessages).toHaveLength(1)
        })

        it('does not run transformations when the killswitch is on', async () => {
            const logsTransformer = await buildTransformer(`return null`)
            transformerConsumer = await createLogsIngestionConsumer(
                hub,
                { LOGS_TRANSFORMATIONS_ENABLED_TEAMS: '*', LOGS_TRANSFORMATIONS_KILLSWITCH: true },
                { logsTransformer }
            )

            const messages = await createKafkaMessages([createLogMessage()], { token: team.api_token })
            await waitForBackgroundTasks(transformerConsumer.processKafkaBatch(messages))

            const logsMessages = getProducedKafkaMessages().filter((m) => m.topic === 'clickhouse_logs_test')
            expect(logsMessages).toHaveLength(1)
        })
    })
})
