import { Message } from 'node-rdkafka'

import { emitIngestionWarning } from '../../ingestion/common/ingestion-warnings'
import { DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT } from '../../ingestion/common/outputs'
import { IngestionOutputs } from '../../ingestion/outputs/ingestion-outputs'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { logDroppedMessage, produceMessageToDLQ, redirectMessageToTopic } from './pipeline-helpers'

// Mock all dependencies
jest.mock('../../utils/logger')
jest.mock('../../utils/posthog')

jest.mock('../../ingestion/common/ingestion-warnings', () => {
    const actual = jest.requireActual('../../ingestion/common/ingestion-warnings')
    return {
        ...actual,
        emitIngestionWarning: jest.fn(),
    }
})

const mockLogger = logger as jest.Mocked<typeof logger>
const mockCaptureException = captureException as jest.MockedFunction<typeof captureException>
const mockEmitIngestionWarning = emitIngestionWarning as jest.MockedFunction<typeof emitIngestionWarning>

function createMockOutputs(mockKafkaProducer: KafkaProducerWrapper) {
    return new IngestionOutputs({
        [DLQ_OUTPUT]: { topic: 'test-dlq', producer: mockKafkaProducer },
        [INGESTION_WARNINGS_OUTPUT]: { topic: 'test-ingestion-warnings', producer: mockKafkaProducer },
    })
}

describe('produceMessageToDLQ', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockOutputs: IngestionOutputs<'dlq' | 'ingestion_warnings'>
    let mockMessage: Message

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            queueMessages: jest.fn() as any,
            produce: jest.fn() as any,
        } as any

        mockOutputs = createMockOutputs(mockKafkaProducer)

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

        mockEmitIngestionWarning.mockResolvedValue(true)
    })

    it('should send message to DLQ with proper headers and logging', async () => {
        const error = new Error('Test error')
        const stepName = 'test-step'

        await produceMessageToDLQ(mockOutputs, mockMessage, error, stepName)

        expect(mockLogger.warn).toHaveBeenCalledWith('Event sent to DLQ', {
            step: stepName,
            team_id: '42',
            uuid: 'test-uuid-123',
            distinct_id: 'test-user',
            event: 'pageview',
            error: 'Test error',
        })

        expect(mockEmitIngestionWarning).toHaveBeenCalledWith(
            mockOutputs,
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
            topic: 'test-dlq',
            value: mockMessage.value,
            key: mockMessage.key,
            headers: expect.objectContaining({
                team_id: '42',
                distinct_id: 'test-user',
                event: 'pageview',
                dlq_reason: 'Test error',
                dlq_step: stepName,
                dlq_timestamp: expect.any(String),
                dlq_topic: 'test-topic',
                dlq_partition: '0',
                dlq_offset: '123',
            }),
        })
    })

    it('should handle message without headers', async () => {
        const messageWithoutHeaders = { ...mockMessage, headers: undefined } as Message
        const error = new Error('Test error')
        const stepName = 'test-step'

        await produceMessageToDLQ(mockOutputs, messageWithoutHeaders, error, stepName)

        expect(mockLogger.warn).toHaveBeenCalledWith('Event sent to DLQ', {
            step: stepName,
            team_id: undefined,
            distinct_id: undefined,
            event: undefined,
            error: 'Test error',
        })

        expect(mockEmitIngestionWarning).not.toHaveBeenCalled()
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

        await produceMessageToDLQ(mockOutputs, messageWithMixedHeaders, error, stepName)

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
            topic: 'test-dlq',
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

        await produceMessageToDLQ(mockOutputs, mockMessage, error, stepName)

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith(
            expect.objectContaining({
                headers: expect.objectContaining({
                    dlq_reason: 'String error',
                }),
            })
        )
    })

    it('should handle DLQ failures gracefully', async () => {
        const error = new Error('Test error')
        const stepName = 'test-step'
        const dlqError = new Error('DLQ failed')

        mockKafkaProducer.produce = jest.fn().mockRejectedValue(dlqError)

        await produceMessageToDLQ(mockOutputs, mockMessage, error, stepName)

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

    it('should correctly process different header types in produceMessageToDLQ', async () => {
        const mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
        } as unknown as KafkaProducerWrapper

        const mockOutputs = createMockOutputs(mockKafkaProducer)

        await produceMessageToDLQ(mockOutputs, mockMessage, new Error('test'), 'test-step')

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
