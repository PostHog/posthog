import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper, TopicMessage } from '../../kafka/producer'
import { PipelineEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import {
    logDroppedMessage,
    redirectEventToTopic,
    redirectMessageToTopic,
    sendEventToDLQ,
    sendMessageToDLQ,
} from './pipeline-helpers'
import { captureIngestionWarning } from './utils'

// Mock all dependencies
jest.mock('../../utils/logger')
jest.mock('../../utils/posthog')

// Mock only specific functions from utils, not the whole module
jest.mock('./utils', () => {
    const actual = jest.requireActual('./utils')
    return {
        ...actual,
        captureIngestionWarning: jest.fn(),
    }
})

const mockLogger = logger as jest.Mocked<typeof logger>
const mockCaptureException = captureException as jest.MockedFunction<typeof captureException>
const mockCaptureIngestionWarning = captureIngestionWarning as jest.MockedFunction<typeof captureIngestionWarning>

describe('sendEventToDLQ', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockEvent: PipelineEvent

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            queueMessages: jest.fn() as any,
            produce: jest.fn() as any,
        } as any

        mockEvent = {
            uuid: 'test-uuid-123',
            distinct_id: 'test-user',
            event: '$pageview',
            team_id: 42,
            properties: { test: 'value' },
            timestamp: '2023-01-01T00:00:00Z',
            ip: null,
            site_url: 'https://example.com',
            now: '2023-01-01T00:00:00Z',
        } as PipelineEvent

        jest.mocked(mockKafkaProducer.queueMessages).mockImplementation(() => Promise.resolve())
        jest.mocked(mockKafkaProducer.produce).mockImplementation(() => Promise.resolve())
        mockCaptureIngestionWarning.mockResolvedValue(true)
    })

    it('should send event to DLQ with proper logging', async () => {
        const error = new Error('Test error')
        const stepName = 'test-step'

        await sendEventToDLQ(mockKafkaProducer, mockEvent, error, stepName)

        expect(mockLogger.warn).toHaveBeenCalledWith('Event sent to DLQ', {
            step: stepName,
            team_id: 42,
            distinct_id: 'test-user',
            event: '$pageview',
            error: 'Test error',
        })

        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockKafkaProducer,
            42,
            'pipeline_step_dlq',
            {
                distinctId: 'test-user',
                eventUuid: 'test-uuid-123',
                error: 'Test error',
                event: '$pageview',
                step: stepName,
            },
            { alwaysSend: true }
        )

        expect(mockKafkaProducer.queueMessages).toHaveBeenCalledTimes(1)

        expect((mockKafkaProducer.queueMessages.mock.calls[0][0] as TopicMessage).topic).toEqual(
            'events_dead_letter_queue_test'
        )

        const dlqMessage = parseJSON(
            (mockKafkaProducer.queueMessages.mock.calls[0][0] as TopicMessage).messages[0].value as string
        )
        expect(dlqMessage).toMatchObject({
            event_uuid: 'test-uuid-123',
            distinct_id: 'test-user',
            event: '$pageview',
            team_id: 42,
            error_location: 'plugin_server_ingest_event:test-step',
            error: 'Event ingestion failed. Error: Test error',
            tags: ['plugin_server', 'ingest_event'],
            site_url: 'https://example.com',
            ip: '',
            properties: '{"test":"value"}',
        })

        // Assert the original event is preserved in raw_payload
        const rawPayload = parseJSON(dlqMessage.raw_payload)
        expect(rawPayload).toMatchObject({
            uuid: 'test-uuid-123',
            distinct_id: 'test-user',
            event: '$pageview',
            team_id: 42,
            properties: { test: 'value' },
            timestamp: '2023-01-01T00:00:00Z',
            ip: null,
            site_url: 'https://example.com',
            now: '2023-01-01T00:00:00Z',
        })

        // Assert generated fields exist
        expect(dlqMessage.id).toBeDefined()
        expect(dlqMessage.error_timestamp).toBeDefined()
        expect(dlqMessage.now).toBeDefined()
    })

    it('should handle event without team_id', async () => {
        const eventWithoutTeamId = { ...mockEvent, team_id: undefined } as PipelineEvent
        const error = new Error('Test error')
        const stepName = 'test-step'

        await sendEventToDLQ(mockKafkaProducer, eventWithoutTeamId, error, stepName)

        expect(mockLogger.warn).toHaveBeenCalledWith('Event sent to DLQ', {
            step: stepName,
            team_id: 0,
            distinct_id: 'test-user',
            event: '$pageview',
            error: 'Test error',
        })
    })

    it('should handle non-Error objects', async () => {
        const error = 'String error'
        const stepName = 'test-step'

        await sendEventToDLQ(mockKafkaProducer, mockEvent, error, stepName)

        expect(mockLogger.warn).toHaveBeenCalledWith('Event sent to DLQ', {
            step: stepName,
            team_id: 42,
            distinct_id: 'test-user',
            event: '$pageview',
            error: 'String error',
        })

        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockKafkaProducer,
            42,
            'pipeline_step_dlq',
            expect.objectContaining({
                error: 'String error',
            }),
            { alwaysSend: true }
        )
    })

    it('should handle DLQ failures gracefully', async () => {
        const error = new Error('Test error')
        const stepName = 'test-step'
        const dlqError = new Error('DLQ failed')

        mockKafkaProducer.queueMessages = jest.fn().mockRejectedValue(dlqError)

        await sendEventToDLQ(mockKafkaProducer, mockEvent, error, stepName)

        expect(mockLogger.error).toHaveBeenCalledWith('Failed to send event to DLQ', {
            step: stepName,
            team_id: 42,
            distinct_id: 'test-user',
            error: dlqError,
        })

        expect(mockCaptureException).toHaveBeenCalledWith(dlqError, {
            tags: { team_id: 42, pipeline_step: stepName },
            extra: { originalEvent: mockEvent, error: dlqError },
        })
    })

    it('should use provided teamId parameter', async () => {
        const error = new Error('Test error')
        const stepName = 'test-step'
        const providedTeamId = 999

        await sendEventToDLQ(mockKafkaProducer, mockEvent, error, stepName, providedTeamId)

        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockKafkaProducer,
            providedTeamId,
            'pipeline_step_dlq',
            expect.objectContaining({
                step: stepName,
            }),
            { alwaysSend: true }
        )
    })
})

describe('redirectEventToTopic', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockEvent: PipelineEvent

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            queueMessages: jest.fn() as any,
            produce: jest.fn() as any,
        } as any

        mockEvent = {
            uuid: 'test-uuid-123',
            distinct_id: 'test-user',
            event: '$pageview',
            team_id: 42,
            properties: { test: 'value' },
            timestamp: '2023-01-01T00:00:00Z',
            ip: null,
            site_url: 'https://example.com',
            now: '2023-01-01T00:00:00Z',
        } as PipelineEvent
    })

    it('should redirect event to topic with default parameters', async () => {
        const topic = 'overflow-topic'
        const stepName = 'test-step'

        await redirectEventToTopic(mockKafkaProducer, mockEvent, topic, stepName)

        expect(mockLogger.info).toHaveBeenCalledWith('Event redirected to topic', {
            step: stepName,
            team_id: 42,
            distinct_id: 'test-user',
            event: '$pageview',
            topic,
        })

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
            topic: topic,
            key: '42:test-user',
            value: Buffer.from(JSON.stringify(mockEvent)),
            headers: {
                distinct_id: 'test-user',
                team_id: '42',
            },
        })

        expect(mockLogger.info).toHaveBeenCalledWith('Event successfully redirected to topic', {
            team_id: 42,
            distinct_id: 'test-user',
            event: '$pageview',
            topic,
        })
    })

    it('should handle preserveKey = false', async () => {
        const topic = 'overflow-topic'
        const stepName = 'test-step'

        await redirectEventToTopic(mockKafkaProducer, mockEvent, topic, stepName, false)

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
            topic: topic,
            key: null,
            value: Buffer.from(JSON.stringify(mockEvent)),
            headers: {
                distinct_id: 'test-user',
                team_id: '42',
            },
        })
    })

    it('should handle awaitAck = false', async () => {
        const topic = 'overflow-topic'
        const stepName = 'test-step'

        // Create a promise that never resolves to ensure we're not awaiting it
        const neverResolvingPromise = new Promise(() => {})
        let produceCalled = false

        mockKafkaProducer.produce = jest.fn().mockImplementation(() => {
            produceCalled = true
            return neverResolvingPromise
        })

        // This should return quickly without waiting for the promise
        await redirectEventToTopic(mockKafkaProducer, mockEvent, topic, stepName, true, false)

        // Verify produce was called but we didn't wait for it
        expect(produceCalled).toBe(true)
        expect(mockKafkaProducer.produce).toHaveBeenCalled()
    })

    it('should handle events without team_id', async () => {
        const eventWithoutTeamId = { ...mockEvent, team_id: undefined } as PipelineEvent
        const topic = 'overflow-topic'

        await redirectEventToTopic(mockKafkaProducer, eventWithoutTeamId, topic)

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
            topic: topic,
            key: '0:test-user',
            value: Buffer.from(JSON.stringify(eventWithoutTeamId)),
            headers: {
                distinct_id: 'test-user',
                team_id: '0',
            },
        })
    })

    it('should handle redirect failures', async () => {
        const topic = 'overflow-topic'
        const stepName = 'test-step'
        const redirectError = new Error('Redirect failed')

        mockKafkaProducer.produce = jest.fn().mockRejectedValue(redirectError)

        await expect(redirectEventToTopic(mockKafkaProducer, mockEvent, topic, stepName)).rejects.toThrow(
            'Redirect failed'
        )

        expect(mockLogger.error).toHaveBeenCalledWith('Failed to redirect event to topic', {
            team_id: 42,
            distinct_id: 'test-user',
            topic,
            error: redirectError,
        })

        expect(mockCaptureException).toHaveBeenCalledWith(redirectError, {
            tags: { team_id: 42, pipeline_step: stepName },
            extra: { originalEvent: mockEvent, topic, error: redirectError },
        })
    })

    it('should use default step name when not provided', async () => {
        const topic = 'overflow-topic'

        await redirectEventToTopic(mockKafkaProducer, mockEvent, topic)

        expect(mockLogger.info).toHaveBeenCalledWith(
            'Event redirected to topic',
            expect.objectContaining({
                step: 'unknown',
            })
        )
    })
})

describe('sendMessageToDLQ', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockMessage: Message

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            queueMessages: jest.fn() as any,
            produce: jest.fn() as any,
        } as any

        mockMessage = {
            value: Buffer.from('test message'),
            topic: 'test-topic',
            partition: 0,
            offset: 123,
            key: 'test-key',
            size: 12,
            headers: [
                { team_id: Buffer.from('42') },
                { distinct_id: Buffer.from('test-user') },
                { event: 'pageview' },
                { uuid: 'test-uuid-123' },
            ],
        } as Message

        mockCaptureIngestionWarning.mockResolvedValue(true)
    })

    it('should send message to DLQ with proper headers and logging', async () => {
        const error = new Error('Test error')
        const stepName = 'test-step'
        const dlqTopic = 'test-dlq'

        await sendMessageToDLQ(mockKafkaProducer, mockMessage, error, stepName, dlqTopic)

        expect(mockLogger.warn).toHaveBeenCalledWith('Event sent to DLQ', {
            step: stepName,
            team_id: '42',
            uuid: 'test-uuid-123',
            distinct_id: 'test-user',
            event: 'pageview',
            error: 'Test error',
        })

        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockKafkaProducer,
            42,
            'pipeline_step_dlq',
            {
                distinctId: 'test-user',
                eventUuid: 'test-uuid-123',
                error: 'Test error',
                event: 'pageview',
                step: stepName,
            },
            { alwaysSend: true }
        )

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
            topic: dlqTopic,
            value: mockMessage.value,
            key: mockMessage.key,
            headers: expect.objectContaining({
                team_id: '42',
                distinct_id: 'test-user',
                event: 'pageview',
                'dlq-reason': 'Test error',
                'dlq-step': stepName,
                'dlq-timestamp': expect.any(String),
            }),
        })
    })

    it('should handle message without headers', async () => {
        const messageWithoutHeaders = { ...mockMessage, headers: undefined } as Message
        const error = new Error('Test error')
        const stepName = 'test-step'
        const dlqTopic = 'test-dlq'

        await sendMessageToDLQ(mockKafkaProducer, messageWithoutHeaders, error, stepName, dlqTopic)

        expect(mockLogger.warn).toHaveBeenCalledWith('Event sent to DLQ', {
            step: stepName,
            team_id: undefined,
            distinct_id: undefined,
            event: undefined,
            error: 'Test error',
        })

        expect(mockCaptureIngestionWarning).not.toHaveBeenCalled()
    })

    it('should handle different header value types', async () => {
        const messageWithMixedHeaders = {
            ...mockMessage,
            headers: [
                { team_id: 42 }, // number
                { distinct_id: 'test-user' }, // string
                { event: Buffer.from('pageview') }, // Buffer
                { custom: null }, // null
                { undefined: undefined }, // undefined
            ],
        } as Message

        const error = new Error('Test error')
        const stepName = 'test-step'
        const dlqTopic = 'test-dlq'

        await sendMessageToDLQ(mockKafkaProducer, messageWithMixedHeaders, error, stepName, dlqTopic)

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
            topic: dlqTopic,
            value: messageWithMixedHeaders.value,
            key: messageWithMixedHeaders.key,
            headers: expect.objectContaining({
                team_id: '42',
                distinct_id: 'test-user',
                event: 'pageview',
                custom: 'null',
                // undefined should not be included
            }),
        })
    })

    it('should handle non-Error objects', async () => {
        const error = 'String error'
        const stepName = 'test-step'
        const dlqTopic = 'test-dlq'

        await sendMessageToDLQ(mockKafkaProducer, mockMessage, error, stepName, dlqTopic)

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith(
            expect.objectContaining({
                headers: expect.objectContaining({
                    'dlq-reason': 'String error',
                }),
            })
        )
    })

    it('should handle DLQ failures gracefully', async () => {
        const error = new Error('Test error')
        const stepName = 'test-step'
        const dlqTopic = 'test-dlq'
        const dlqError = new Error('DLQ failed')

        mockKafkaProducer.produce = jest.fn().mockRejectedValue(dlqError)

        await sendMessageToDLQ(mockKafkaProducer, mockMessage, error, stepName, dlqTopic)

        expect(mockLogger.error).toHaveBeenCalledWith('Failed to send event to DLQ', {
            step: stepName,
            uuid: 'test-uuid-123',
            event: 'pageview',
            team_id: '42',
            distinct_id: 'test-user',
            error: dlqError,
        })

        expect(mockCaptureException).toHaveBeenCalledWith(dlqError, {
            tags: { team_id: '42', pipeline_step: stepName },
            extra: { originalMessage: mockMessage, error: dlqError },
        })
    })

    it('should log warning and not send message when DLQ topic is empty', async () => {
        const error = new Error('Test error')
        const stepName = 'test-step'
        const dlqTopic = ''

        await sendMessageToDLQ(mockKafkaProducer, mockMessage, error, stepName, dlqTopic)

        expect(mockLogger.warn).toHaveBeenCalledWith(
            'DLQ topic not configured - message would be sent to DLQ but no topic specified',
            {
                step: stepName,
                team_id: '42',
                uuid: 'test-uuid-123',
                distinct_id: 'test-user',
                event: 'pageview',
                error: 'Test error',
            }
        )

        expect(mockKafkaProducer.produce).not.toHaveBeenCalled()
        expect(mockCaptureIngestionWarning).not.toHaveBeenCalled()
    })
})

describe('redirectMessageToTopic', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockPromiseScheduler: PromiseScheduler
    let mockMessage: Message

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            queueMessages: jest.fn() as any,
            produce: jest.fn() as any,
        } as any

        mockPromiseScheduler = {
            schedule: jest.fn().mockImplementation((promise) => promise),
        } as unknown as PromiseScheduler

        mockMessage = {
            value: Buffer.from('test message'),
            topic: 'test-topic',
            partition: 0,
            offset: 123,
            key: 'test-key',
            size: 12,
            headers: [{ team_id: Buffer.from('42') }, { distinct_id: Buffer.from('test-user') }, { event: 'pageview' }],
        } as Message
    })

    it('should redirect message to topic with default parameters', async () => {
        const topic = 'overflow-topic'
        const stepName = 'test-step'

        await redirectMessageToTopic(mockKafkaProducer, mockPromiseScheduler, mockMessage, topic, stepName)

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
            topic: topic,
            value: mockMessage.value,
            key: mockMessage.key,
            headers: expect.objectContaining({
                team_id: '42',
                distinct_id: 'test-user',
                event: 'pageview',
                'redirect-step': stepName,
                'redirect-timestamp': expect.any(String),
            }),
        })

        expect(mockPromiseScheduler.schedule).toHaveBeenCalled()
    })

    it('should handle preserveKey = false', async () => {
        const topic = 'overflow-topic'
        const stepName = 'test-step'

        await redirectMessageToTopic(mockKafkaProducer, mockPromiseScheduler, mockMessage, topic, stepName, false)

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
            topic: topic,
            value: mockMessage.value,
            key: null,
            headers: expect.any(Object),
        })
    })

    it('should handle awaitAck = false', async () => {
        const topic = 'overflow-topic'
        const stepName = 'test-step'

        // Create a promise that never resolves to ensure we're not awaiting it
        const neverResolvingPromise = new Promise(() => {})
        let produceCalled = false
        let scheduleCalled = false

        mockKafkaProducer.produce = jest.fn().mockImplementation(() => {
            produceCalled = true
            return neverResolvingPromise
        })

        mockPromiseScheduler.schedule = jest.fn().mockImplementation((promise) => {
            scheduleCalled = true
            return promise // Return the never-resolving promise
        })

        // This should return quickly without waiting for the promise
        await redirectMessageToTopic(mockKafkaProducer, mockPromiseScheduler, mockMessage, topic, stepName, true, false)

        // Verify produce and schedule were called but we didn't wait for them
        expect(produceCalled).toBe(true)
        expect(scheduleCalled).toBe(true)
        expect(mockKafkaProducer.produce).toHaveBeenCalled()
        expect(mockPromiseScheduler.schedule).toHaveBeenCalled()
    })

    it('should handle redirect failures', async () => {
        const topic = 'overflow-topic'
        const stepName = 'test-step'
        const redirectError = new Error('Redirect failed')

        mockKafkaProducer.produce = jest.fn().mockRejectedValue(redirectError)

        await expect(
            redirectMessageToTopic(mockKafkaProducer, mockPromiseScheduler, mockMessage, topic, stepName)
        ).rejects.toThrow('Redirect failed')

        expect(mockCaptureException).toHaveBeenCalledWith(redirectError, {
            tags: {
                team_id: '42',
                pipeline_step: stepName,
            },
            extra: {
                topic,
                distinct_id: 'test-user',
                event: 'pageview',
                error: redirectError,
            },
        })
    })

    it('should use default step name when not provided', async () => {
        const topic = 'overflow-topic'

        await redirectMessageToTopic(mockKafkaProducer, mockPromiseScheduler, mockMessage, topic)
    })
})

describe('logDroppedMessage', () => {
    let mockMessage: Message

    beforeEach(() => {
        jest.clearAllMocks()

        mockMessage = {
            value: Buffer.from('test message'),
            topic: 'test-topic',
            partition: 0,
            offset: 123,
            key: 'test-key',
            size: 12,
            headers: [{ team_id: Buffer.from('42') }, { distinct_id: Buffer.from('test-user') }, { event: 'pageview' }],
        } as Message
    })

    it('should log dropped message with proper metadata', () => {
        const reason = 'Invalid format'
        const stepName = 'test-step'

        logDroppedMessage(mockMessage, reason, stepName)

        expect(mockLogger.debug).toHaveBeenCalledWith('Event dropped', {
            step: stepName,
            team_id: '42',
            distinct_id: 'test-user',
            event: 'pageview',
            reason,
        })
    })

    it('should handle message without headers', () => {
        const messageWithoutHeaders = { ...mockMessage, headers: undefined } as Message
        const reason = 'Invalid format'
        const stepName = 'test-step'

        logDroppedMessage(messageWithoutHeaders, reason, stepName)

        expect(mockLogger.debug).toHaveBeenCalledWith('Event dropped', {
            step: stepName,
            team_id: undefined,
            distinct_id: undefined,
            event: undefined,
            reason,
        })
    })

    it('should use default step name when not provided', () => {
        const reason = 'Invalid format'

        logDroppedMessage(mockMessage, reason)

        expect(mockLogger.debug).toHaveBeenCalledWith(
            'Event dropped',
            expect.objectContaining({
                step: 'unknown',
            })
        )
    })
})

describe('Header processing utilities', () => {
    let mockMessage: Message

    beforeEach(() => {
        mockMessage = {
            value: Buffer.from('test message'),
            topic: 'test-topic',
            partition: 0,
            offset: 123,
            key: 'test-key',
            size: 12,
            headers: [
                { stringHeader: 'string-value' },
                { bufferHeader: Buffer.from('buffer-value') },
                { numberHeader: 42 },
                { nullHeader: null },
                { undefinedHeader: undefined },
            ],
        } as Message
    })

    it('should correctly process different header types in sendMessageToDLQ', async () => {
        const mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
        } as unknown as KafkaProducerWrapper

        await sendMessageToDLQ(mockKafkaProducer, mockMessage, new Error('test'), 'test-step', 'dlq-topic')

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith(
            expect.objectContaining({
                headers: expect.objectContaining({
                    stringHeader: 'string-value',
                    bufferHeader: 'buffer-value',
                    numberHeader: '42',
                    nullHeader: 'null',
                    // undefinedHeader should not be present
                }),
            })
        )
    })

    it('should correctly process different header types in redirectMessageToTopic', async () => {
        const mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
        } as unknown as KafkaProducerWrapper

        const mockPromiseScheduler = {
            schedule: jest.fn().mockImplementation((promise) => promise),
        } as unknown as PromiseScheduler

        await redirectMessageToTopic(mockKafkaProducer, mockPromiseScheduler, mockMessage, 'test-topic', 'test-step')

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith(
            expect.objectContaining({
                headers: expect.objectContaining({
                    stringHeader: 'string-value',
                    bufferHeader: 'buffer-value',
                    numberHeader: '42',
                    nullHeader: 'null',
                    // undefinedHeader should not be present
                }),
            })
        )
    })
})
