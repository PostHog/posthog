import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { forSnapshot } from '~/tests/helpers/snapshots'
import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { LogsIngestionConsumer, logMessageDroppedCounter } from './logs-ingestion-consumer'

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
        const team2Id = await createTeam(hub.db.postgres, team.organization_id)
        team2 = (await getTeam(hub, team2Id))!

        consumer = await createLogsIngestionConsumer(hub)
        logMessageDroppedCounterSpy = jest.spyOn(logMessageDroppedCounter, 'inc')
    })

    afterEach(async () => {
        await consumer.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

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

            await consumer.processKafkaBatch(messages)

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

            await consumer.processKafkaBatch(messages)

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

            await consumer.processKafkaBatch(messages)

            expect(mockProducerObserver.getProducedKafkaMessages()).toHaveLength(0)
        })

        it('should drop messages with invalid token', async () => {
            const logData = createLogMessage()
            const messages = createKafkaMessages([logData], {
                token: 'invalid-token',
            })

            await consumer.processKafkaBatch(messages)

            expect(mockProducerObserver.getProducedKafkaMessages()).toHaveLength(0)
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

            await consumer.processKafkaBatch(messages)

            expect(mockProducerObserver.getProducedMessages()).toHaveLength(0)
            expect(logMessageDroppedCounterSpy).toHaveBeenCalledWith({ reason: 'team_not_found' })
        })
    })

    describe('batch processing', () => {
        it('should handle empty batch', async () => {
            const result = await consumer.processBatch([])

            expect(result.backgroundTask).toBeDefined()
            expect(result.messages).toEqual([])
            await result.backgroundTask
        })

        it('should process batch with valid messages', async () => {
            const logData = createLogMessage()
            const messages = createKafkaMessages([logData], {
                token: team.api_token,
            })

            await consumer.processKafkaBatch(messages)

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

            await consumer.processKafkaBatch(messages)

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

            await expect(consumer.processKafkaBatch(messages)).rejects.toThrow('Producer error')

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

            await consumer.processKafkaBatch(messages)

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

            await consumer.processKafkaBatch(messages)

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

            await consumer.processKafkaBatch(messages)

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

            await consumer.processKafkaBatch(messages)

            const producedMessages = mockProducerObserver.getProducedMessages()
            expect(producedMessages).toHaveLength(1)
            expect(producedMessages[0].messages[0].value).toEqual(binaryData)
        })
    })
})
