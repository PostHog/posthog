import { Message } from 'node-rdkafka'

import { createMockIngestionOutputs } from '../../../tests/helpers/mock-ingestion-outputs'
import { emitIngestionWarning } from '../../ingestion/common/ingestion-warnings'
import { DLQ_OUTPUT } from '../../ingestion/common/outputs'
import { IngestionOutputs } from '../../ingestion/outputs/ingestion-outputs'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { logDroppedMessage, produceMessageToDLQ, redirectMessageToOutput } from './pipeline-helpers'

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

describe('produceMessageToDLQ', () => {
    let mockOutputs: jest.Mocked<IngestionOutputs<'dlq' | 'ingestion_warnings'>>
    let mockMessage: Message

    beforeEach(() => {
        jest.clearAllMocks()

        mockOutputs = createMockIngestionOutputs<'dlq' | 'ingestion_warnings'>()

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

        expect(mockOutputs.produce).toHaveBeenCalledWith(DLQ_OUTPUT, {
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

        expect(mockOutputs.produce).toHaveBeenCalledWith(DLQ_OUTPUT, {
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

        expect(mockOutputs.produce).toHaveBeenCalledWith(
            DLQ_OUTPUT,
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

        mockOutputs.produce.mockRejectedValue(dlqError)

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

describe('redirectMessageToOutput', () => {
    const TEST_REDIRECT = 'test_redirect' as const

    let mockOutputs: jest.Mocked<IngestionOutputs<typeof TEST_REDIRECT>>
    let mockPromiseScheduler: PromiseScheduler
    let mockMessage: Message

    beforeEach(() => {
        jest.clearAllMocks()

        mockOutputs = {
            produce: jest.fn().mockResolvedValue(undefined),
            queueMessages: jest.fn().mockResolvedValue(undefined),
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

    it('should redirect message to output with default parameters', async () => {
        const stepName = 'test-step'

        await redirectMessageToOutput(mockOutputs, TEST_REDIRECT, mockPromiseScheduler, mockMessage, stepName)

        expect(mockOutputs.produce).toHaveBeenCalledWith(TEST_REDIRECT, {
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
        const stepName = 'test-step'

        await redirectMessageToOutput(mockOutputs, TEST_REDIRECT, mockPromiseScheduler, mockMessage, stepName, false)

        expect(mockOutputs.produce).toHaveBeenCalledWith(TEST_REDIRECT, {
            value: mockMessage.value,
            key: null,
            headers: expect.any(Object),
        })
    })

    it('should handle awaitAck = false', async () => {
        const stepName = 'test-step'

        const neverResolvingPromise = new Promise(() => {})
        mockOutputs.produce = jest.fn().mockReturnValue(neverResolvingPromise)

        mockPromiseScheduler.schedule = jest.fn().mockImplementation((promise) => promise)

        await redirectMessageToOutput(
            mockOutputs,
            TEST_REDIRECT,
            mockPromiseScheduler,
            mockMessage,
            stepName,
            true,
            false
        )

        expect(mockOutputs.produce).toHaveBeenCalled()
        expect(mockPromiseScheduler.schedule).toHaveBeenCalled()
    })

    it('should handle redirect failures', async () => {
        const stepName = 'test-step'
        const redirectError = new Error('Redirect failed')

        mockOutputs.produce = jest.fn().mockRejectedValue(redirectError)

        await expect(
            redirectMessageToOutput(mockOutputs, TEST_REDIRECT, mockPromiseScheduler, mockMessage, stepName)
        ).rejects.toThrow('Redirect failed')

        expect(mockCaptureException).toHaveBeenCalledWith(redirectError, {
            tags: {
                team_id: '42',
                pipeline_step: stepName,
            },
            extra: {
                output: TEST_REDIRECT,
                distinct_id: 'test-user',
                event: 'pageview',
                error: redirectError,
            },
        })
    })

    it('should use default step name when not provided', async () => {
        await redirectMessageToOutput(mockOutputs, TEST_REDIRECT, mockPromiseScheduler, mockMessage)
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
        const headerMockOutputs = createMockIngestionOutputs<'dlq' | 'ingestion_warnings'>()

        await produceMessageToDLQ(headerMockOutputs, mockMessage, new Error('test'), 'test-step')

        expect(headerMockOutputs.produce).toHaveBeenCalledWith(
            DLQ_OUTPUT,
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

    it('should correctly process different header types in redirectMessageToOutput', async () => {
        const TEST_REDIRECT = 'test_redirect' as const
        const mockRedirectOutputs = {
            produce: jest.fn().mockResolvedValue(undefined),
        } as unknown as IngestionOutputs<typeof TEST_REDIRECT>

        const mockPromiseScheduler = {
            schedule: jest.fn().mockImplementation((promise) => promise),
        } as unknown as PromiseScheduler

        await redirectMessageToOutput(
            mockRedirectOutputs,
            TEST_REDIRECT,
            mockPromiseScheduler,
            mockMessage,
            'test-step'
        )

        expect(mockRedirectOutputs.produce).toHaveBeenCalledWith(
            TEST_REDIRECT,
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
