import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { deleteKeysWithPrefix } from '~/cdp/_tests/redis'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { KAFKA_APP_METRICS_2 } from '../config/kafka-topics'
import { parseJSON } from '../utils/json-parse'
import {
    LogsIngestionConsumer,
    logMessageDroppedCounter,
    logsBytesAllowedCounter,
    logsBytesDroppedCounter,
    logsBytesReceivedCounter,
    logsRecordsAllowedCounter,
    logsRecordsDroppedCounter,
    logsRecordsReceivedCounter,
} from './logs-ingestion-consumer'
import { BASE_REDIS_KEY } from './services/logs-rate-limiter.service'

const DEFAULT_TEST_TIMEOUT = 5000
jest.setTimeout(DEFAULT_TEST_TIMEOUT)

jest.mock('../utils/posthog', () => {
    const original = jest.requireActual('../utils/posthog')
    return {
        ...original,
        captureException: jest.fn(),
    }
})

let offsetIncrementer = 0

const createKafkaMessage = (logData: any, headers: Record<string, string> = {}): Message => {
    return {
        key: null,
        value: Buffer.from(JSON.stringify(logData)),
        size: 1,
        topic: 'test',
        offset: offsetIncrementer++,
        timestamp: DateTime.now().toMillis(),
        partition: 1,
        headers: Object.entries(headers).map(([key, value]) => ({
            [key]: Buffer.from(value),
        })),
    }
}

const createKafkaMessages: (logData: any[], headers?: Record<string, string>) => Message[] = (
    logData,
    headers = {}
) => {
    return logData.map((data) => createKafkaMessage(data, headers))
}

describe('LogsIngestionConsumer', () => {
    let consumer: LogsIngestionConsumer
    let hub: Hub
    let team: Team
    let team2: Team
    let fixedTime: DateTime
    let logMessageDroppedCounterSpy: jest.SpyInstance

    const createLogsIngestionConsumer = async (hub: Hub, overrides: any = {}) => {
        const consumer = new LogsIngestionConsumer(hub, overrides)
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

        team = await getFirstTeam(hub)
        const team2Id = await createTeam(hub.postgres, team.organization_id)
        team2 = (await getTeam(hub, team2Id))!

        consumer = await createLogsIngestionConsumer(hub)

        await deleteKeysWithPrefix(consumer['redis'], BASE_REDIS_KEY)
        logMessageDroppedCounterSpy = jest.spyOn(logMessageDroppedCounter, 'inc')
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

    describe('general', () => {
        it('should have the correct config', () => {
            expect(consumer['name']).toEqual('LogsIngestionConsumer')
            expect(consumer['groupId']).toEqual('ingestion-logs')
            expect(consumer['topic']).toEqual('logs_ingestion_test')
            expect(consumer['clickhouseTopic']).toEqual('clickhouse_logs_test')
            expect(consumer['overflowTopic']).toEqual('logs_ingestion_overflow_test')
            expect(consumer['dlqTopic']).toEqual('logs_ingestion_dlq_test')
        })

        it('should allow config overrides', async () => {
            const overrides = {
                LOGS_INGESTION_CONSUMER_GROUP_ID: 'custom-group',
                LOGS_INGESTION_CONSUMER_CONSUME_TOPIC: 'custom-topic',
                LOGS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC: 'custom-clickhouse-topic',
            }
            const customConsumer = await createLogsIngestionConsumer(hub, overrides)

            expect(customConsumer['groupId']).toBe('custom-group')
            expect(customConsumer['topic']).toBe('custom-topic')
            expect(customConsumer['clickhouseTopic']).toBe('custom-clickhouse-topic')

            await customConsumer.stop()
        })

        it('should process a valid log message', async () => {
            const logData = createLogMessage()
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            expect(forSnapshot(mockProducerObserver.getProducedKafkaMessages())).toMatchSnapshot()
        })

        it('should process multiple log messages', async () => {
            const logData = [
                createLogMessage({ level: 'info', message: 'First log' }),
                createLogMessage({ level: 'error', message: 'Second log' }),
                createLogMessage({ level: 'debug', message: 'Third log' }),
            ]
            const messages = createKafkaMessages(logData, {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = mockProducerObserver.getProducedKafkaMessages()
            expect(producedMessages).toHaveLength(3)
            expect(forSnapshot(producedMessages)).toMatchSnapshot()
        })
    })

    describe('message parsing and validation', () => {
        it('should drop messages with missing token', async () => {
            const logData = createLogMessage()
            const messages = createKafkaMessages([logData], {
                // missing token
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            expect(mockProducerObserver.getProducedKafkaMessages()).toHaveLength(0)
        })

        it('should drop messages with invalid token', async () => {
            const logData = createLogMessage()
            const messages = createKafkaMessages([logData], {
                token: 'invalid-token',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            expect(mockProducerObserver.getProducedKafkaMessages()).toHaveLength(0)
        })

        it('should preserve kafka message headers', async () => {
            const logData = createLogMessage()
            const messages = createKafkaMessages([logData], {
                myHeader: 'hello',
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = mockProducerObserver.getProducedKafkaMessages()
            expect(forSnapshot(producedMessages)).toMatchSnapshot()
        })

        it('should overwrite existing headers', async () => {
            const logData = createLogMessage()
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
                team_id: '999',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))
            expect(forSnapshot(mockProducerObserver.getProducedKafkaMessages())).toMatchSnapshot()
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

            expect(mockProducerObserver.getProducedMessages()).toHaveLength(0)
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith({ reason: 'team_not_found' })
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
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = mockProducerObserver.getProducedKafkaMessages()
            expect(producedMessages).toHaveLength(1)
            expect(producedMessages[0].topic).toBe('clickhouse_logs_test')
            expect(producedMessages[0].headers).toEqual({
                token: team.api_token,
                team_id: team.id.toString(),
            })
        })

        it('should produce messages with correct headers', async () => {
            const logData = createLogMessage({ level: 'error', message: 'Critical error' })
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = mockProducerObserver.getProducedMessages()
            expect(producedMessages).toHaveLength(1)

            const message = producedMessages[0]
            expect(message.topic).toBe('clickhouse_logs_test')
            expect(message.messages).toHaveLength(1)
            expect(message.messages[0].key).toBeNull()
            expect(message.messages[0].headers).toEqual({
                token: team.api_token,
                team_id: team.id.toString(),
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
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
            })

            // Mock producer to throw an error
            const originalProduce = consumer['kafkaProducer']!.produce
            consumer['kafkaProducer']!.produce = jest.fn().mockRejectedValue(new Error('Producer error'))

            await expect(waitForBackgroundTasks(consumer.processKafkaBatch(messages))).rejects.toThrow('Producer error')

            // Restore original method
            consumer['kafkaProducer']!.produce = originalProduce
        })
    })

    describe('message routing', () => {
        it('should route messages to correct ClickHouse topic', async () => {
            const logData = createLogMessage()
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = mockProducerObserver.getProducedKafkaMessages()
            expect(producedMessages).toHaveLength(1)
            expect(producedMessages[0].topic).toBe('clickhouse_logs_test')
        })

        it('should handle messages from different teams', async () => {
            const logData1 = createLogMessage({ message: 'Team 1 log' })
            const logData2 = createLogMessage({ message: 'Team 2 log' })

            const messages = [
                ...createKafkaMessages([logData1], {
                    token: team.api_token,
                }),
                ...createKafkaMessages([logData2], {
                    token: team2.api_token,
                }),
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = mockProducerObserver.getProducedKafkaMessages()
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

            const messages = createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const producedMessages = mockProducerObserver.getProducedMessages()
            expect(producedMessages).toHaveLength(1)

            expect(producedMessages[0].messages[0].value).toEqual(messages[0].value)
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
                ...createKafkaMessages([logData1], {
                    token: team.api_token,
                    bytes_uncompressed: '1024',
                    bytes_compressed: '512',
                    record_count: '5',
                }),
                ...createKafkaMessages([logData2], {
                    token: team.api_token,
                    bytes_uncompressed: '2048',
                    bytes_compressed: '1024',
                    record_count: '10',
                }),
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            // Filter to only the logs topic (excludes app_metrics2 messages)
            const logsMessages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === 'clickhouse_logs_test')
            expect(logsMessages).toHaveLength(1)
            expect(bytesReceivedSpy).toHaveBeenCalledWith(3072)
            expect(bytesAllowedSpy).toHaveBeenCalledWith(1024)
            expect(bytesDroppedSpy).toHaveBeenCalledWith(2048)
            expect(recordsReceivedSpy).toHaveBeenCalledWith(15)
            expect(recordsAllowedSpy).toHaveBeenCalledWith(5)
            expect(recordsDroppedSpy).toHaveBeenCalledWith(10)
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith({ reason: 'rate_limited' }, 1)
        })

        it('should handle missing header values with defaults', async () => {
            const logData = createLogMessage()
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            expect(mockProducerObserver.getProducedKafkaMessages()).toHaveLength(1)
            expect(bytesReceivedSpy).toHaveBeenCalledWith(0)
            expect(recordsReceivedSpy).toHaveBeenCalledWith(0)
        })
    })

    describe('filterRateLimitedMessages', () => {
        it('should return usageStats with correct structure for allowed messages', async () => {
            const logData = createLogMessage()
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
                bytes_uncompressed: '1024',
                record_count: '5',
            })

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const { allowed, usageStats } = await consumer['filterRateLimitedMessages'](parsed)

            expect(allowed).toHaveLength(1)
            expect(usageStats.size).toBe(1)

            const stats = usageStats.get(team.id)
            expect(stats).toBeDefined()
            expect(stats!.bytesReceived).toBe(1024)
            expect(stats!.recordsReceived).toBe(5)
            expect(stats!.bytesAllowed).toBe(1024)
            expect(stats!.recordsAllowed).toBe(5)
            expect(stats!.bytesDropped).toBe(0)
            expect(stats!.recordsDropped).toBe(0)
        })

        it('should aggregate stats for multiple messages from same team', async () => {
            const messages = [
                ...createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '100',
                    record_count: '1',
                }),
                ...createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '200',
                    record_count: '2',
                }),
            ]

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const { usageStats } = await consumer['filterRateLimitedMessages'](parsed)

            const stats = usageStats.get(team.id)
            expect(stats!.bytesReceived).toBe(300)
            expect(stats!.recordsReceived).toBe(3)
            expect(stats!.bytesAllowed).toBe(300)
            expect(stats!.recordsAllowed).toBe(3)
        })

        it('should track separate stats for different teams', async () => {
            const messages = [
                ...createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '100',
                    record_count: '1',
                }),
                ...createKafkaMessages([createLogMessage()], {
                    token: team2.api_token,
                    bytes_uncompressed: '200',
                    record_count: '2',
                }),
            ]

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const { usageStats } = await consumer['filterRateLimitedMessages'](parsed)

            expect(usageStats.size).toBe(2)
            expect(usageStats.get(team.id)!.bytesAllowed).toBe(100)
            expect(usageStats.get(team2.id)!.bytesAllowed).toBe(200)
        })

        it('should track dropped stats when rate limited', async () => {
            hub.LOGS_LIMITER_BUCKET_SIZE_KB = 1 // 1024 bytes - allows first message
            hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND = 0.001
            hub.LOGS_LIMITER_TTL_SECONDS = 3600

            await consumer.stop()
            consumer = await createLogsIngestionConsumer(hub)

            const messages = [
                ...createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '512', // Fits in bucket
                    record_count: '1',
                }),
                ...createKafkaMessages([createLogMessage()], {
                    token: team.api_token,
                    bytes_uncompressed: '2048', // Exceeds remaining bucket
                    record_count: '5',
                }),
            ]

            const parsed = await consumer['_parseKafkaBatch'](messages)
            const { allowed, usageStats } = await consumer['filterRateLimitedMessages'](parsed)

            expect(allowed).toHaveLength(1)
            const stats = usageStats.get(team.id)
            expect(stats!.bytesReceived).toBe(2560)
            expect(stats!.bytesAllowed).toBe(512)
            expect(stats!.bytesDropped).toBe(2048)
            expect(stats!.recordsDropped).toBe(5)
        })
    })

    describe('produceUsageMetric', () => {
        it('should produce metric with correct structure', async () => {
            await consumer['produceUsageMetric'](123, 'test_metric', 500, '2025-01-01 00:00:00.000')

            const messages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

            expect(messages).toHaveLength(1)
            const value = messages[0].value
            expect(value.team_id).toBe(123)
            expect(value.app_source).toBe('logs')
            expect(value.app_source_id).toBe('')
            expect(value.instance_id).toBe('')
            expect(value.metric_kind).toBe('usage')
            expect(value.metric_name).toBe('test_metric')
            expect(value.count).toBe(500)
            expect(value.timestamp).toBe('2025-01-01 00:00:00.000')
        })

        it('should not produce metric when count is zero', async () => {
            await consumer['produceUsageMetric'](123, 'test_metric', 0, '2025-01-01 00:00:00.000')

            const messages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

            expect(messages).toHaveLength(0)
        })
    })

    describe('emitUsageMetrics', () => {
        it('should emit all metric types for each team', async () => {
            const usageStats = new Map([
                [
                    team.id,
                    {
                        bytesReceived: 1000,
                        recordsReceived: 10,
                        bytesAllowed: 800,
                        recordsAllowed: 8,
                        bytesDropped: 200,
                        recordsDropped: 2,
                    },
                ],
            ])

            await consumer['emitUsageMetrics'](usageStats)

            const messages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

            expect(messages).toHaveLength(6)

            const metricNames = messages.map((m) => m.value.metric_name)
            expect(metricNames).toContain('bytes_received')
            expect(metricNames).toContain('records_received')
            expect(metricNames).toContain('bytes_ingested')
            expect(metricNames).toContain('records_ingested')
            expect(metricNames).toContain('bytes_dropped')
            expect(metricNames).toContain('records_dropped')
        })

        it('should skip zero-count metrics', async () => {
            const usageStats = new Map([
                [
                    team.id,
                    {
                        bytesReceived: 1000,
                        recordsReceived: 10,
                        bytesAllowed: 1000,
                        recordsAllowed: 10,
                        bytesDropped: 0,
                        recordsDropped: 0,
                    },
                ],
            ])

            await consumer['emitUsageMetrics'](usageStats)

            const messages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

            // Should only have 4 metrics (no dropped)
            expect(messages).toHaveLength(4)
            const metricNames = messages.map((m) => m.value.metric_name)
            expect(metricNames).not.toContain('bytes_dropped')
            expect(metricNames).not.toContain('records_dropped')
        })

        it('should handle empty usageStats', async () => {
            const usageStats = new Map()

            await consumer['emitUsageMetrics'](usageStats)

            const messages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

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
                        bytesDropped: 0,
                        recordsDropped: 0,
                    },
                ],
                [
                    team2.id,
                    {
                        bytesReceived: 200,
                        recordsReceived: 2,
                        bytesAllowed: 200,
                        recordsAllowed: 2,
                        bytesDropped: 0,
                        recordsDropped: 0,
                    },
                ],
            ])

            await consumer['emitUsageMetrics'](usageStats)

            const messages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

            // 4 metrics per team (no dropped) = 8 total
            expect(messages).toHaveLength(8)

            const team1Messages = messages.filter((m) => m.value.team_id === team.id)
            const team2Messages = messages.filter((m) => m.value.team_id === team2.id)
            expect(team1Messages).toHaveLength(4)
            expect(team2Messages).toHaveLength(4)
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
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
                bytes_uncompressed: '1024',
                record_count: '5',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

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

        it('should emit correct metric values per team', async () => {
            const logData = createLogMessage()
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
                bytes_uncompressed: '2048',
                record_count: '10',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

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
                ...createKafkaMessages([logData1], {
                    token: team.api_token,
                    bytes_uncompressed: '512',
                    record_count: '2',
                }),
                ...createKafkaMessages([logData2], {
                    token: team.api_token,
                    bytes_uncompressed: '2048',
                    record_count: '8',
                }),
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

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
                ...createKafkaMessages([logData1], {
                    token: team.api_token,
                    bytes_uncompressed: '100',
                    record_count: '1',
                }),
                ...createKafkaMessages([logData2], {
                    token: team.api_token,
                    bytes_uncompressed: '200',
                    record_count: '2',
                }),
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

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
                ...createKafkaMessages([logData1], {
                    token: team.api_token,
                    bytes_uncompressed: '100',
                    record_count: '1',
                }),
                ...createKafkaMessages([logData2], {
                    token: team2.api_token,
                    bytes_uncompressed: '200',
                    record_count: '2',
                }),
            ]

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

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
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
                bytes_uncompressed: '100',
                record_count: '1',
            })

            await waitForBackgroundTasks(consumer.processKafkaBatch(messages))

            const appMetricsMessages = mockProducerObserver
                .getProducedKafkaMessages()
                .filter((m) => m.topic === KAFKA_APP_METRICS_2)

            // Should not have bytes_dropped or records_dropped since nothing was dropped
            const droppedMetrics = appMetricsMessages.filter((m) => {
                const value = parseMetricValue(m.value)
                return value.metric_name === 'bytes_dropped' || value.metric_name === 'records_dropped'
            })

            expect(droppedMetrics).toHaveLength(0)
        })
    })
})
