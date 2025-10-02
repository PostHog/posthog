import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { pipelineLastStepCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { logDroppedMessage, redirectMessageToTopic, sendMessageToDLQ } from '../../worker/ingestion/pipeline-helpers'
import { BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { createNewBatchPipeline } from './helpers'
import { PipelineConfig, ResultHandlingPipeline } from './result-handling-pipeline'
import { dlq, drop, ok, redirect } from './results'

// Mock the pipeline helpers
jest.mock('../../worker/ingestion/pipeline-helpers', () => ({
    logDroppedMessage: jest.fn(),
    redirectMessageToTopic: jest.fn(),
    sendMessageToDLQ: jest.fn(),
}))

// Mock the metrics
jest.mock('../../worker/ingestion/event-pipeline/metrics', () => ({
    pipelineLastStepCounter: {
        labels: jest.fn().mockReturnValue({
            inc: jest.fn(),
        }),
    },
}))

const mockLogDroppedMessage = logDroppedMessage as jest.MockedFunction<typeof logDroppedMessage>
const mockRedirectMessageToTopic = redirectMessageToTopic as jest.MockedFunction<typeof redirectMessageToTopic>
const mockSendMessageToDLQ = sendMessageToDLQ as jest.MockedFunction<typeof sendMessageToDLQ>
const mockPipelineLastStepCounter = pipelineLastStepCounter as jest.Mocked<typeof pipelineLastStepCounter>

describe('ResultHandlingPipeline', () => {
    let mockKafkaProducer: KafkaProducerWrapper
    let mockPromiseScheduler: PromiseScheduler
    let config: PipelineConfig

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            producer: {} as any,
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockPromiseScheduler = {
            schedule: jest.fn(),
        } as unknown as PromiseScheduler

        config = {
            kafkaProducer: mockKafkaProducer,
            dlqTopic: 'test-dlq',
            promiseScheduler: mockPromiseScheduler,
        }
    })

    describe('basic functionality', () => {
        it('should process successful results and return values', async () => {
            const messages: Message[] = [
                { value: Buffer.from('test1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('test2'), topic: 'test', partition: 0, offset: 2 } as Message,
            ]

            // Create batch results directly
            const batchResults: BatchPipelineResultWithContext<any> = [
                { result: ok({ processed: 'test1' }), context: { message: messages[0] } },
                { result: ok({ processed: 'test2' }), context: { message: messages[1] } },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([{ processed: 'test1' }, { processed: 'test2' }])
        })

        it('should handle empty batch', async () => {
            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed([])
            const results = await resultPipeline.next()

            expect(results).toBeNull()
        })
    })

    describe('result handling', () => {
        it('should filter out dropped results and log them', async () => {
            const messages: Message[] = [
                { value: Buffer.from('test1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('drop'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('test3'), topic: 'test', partition: 0, offset: 3 } as Message,
            ]

            // Create batch results directly
            const batchResults: BatchPipelineResultWithContext<any> = [
                { result: ok({ processed: 'test1' }), context: { message: messages[0] } },
                { result: drop('test drop reason'), context: { message: messages[1] } },
                { result: ok({ processed: 'test3' }), context: { message: messages[2] } },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([{ processed: 'test1' }, { processed: 'test3' }])
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(messages[1], 'test drop reason', 'unknown')
        })

        it('should filter out redirected results and redirect them', async () => {
            const messages: Message[] = [
                { value: Buffer.from('test1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('redirect'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('test3'), topic: 'test', partition: 0, offset: 3 } as Message,
            ]

            // Create batch results directly
            const batchResults: BatchPipelineResultWithContext<any> = [
                { result: ok({ processed: 'test1' }), context: { message: messages[0] } },
                { result: redirect('test redirect', 'overflow-topic', true, false), context: { message: messages[1] } },
                { result: ok({ processed: 'test3' }), context: { message: messages[2] } },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([{ processed: 'test1' }, { processed: 'test3' }])
            expect(mockRedirectMessageToTopic).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockPromiseScheduler,
                messages[1],
                'overflow-topic',
                'unknown',
                true,
                false
            )
        })

        it('should redirect messages with event and uuid headers', async () => {
            const messagesWithHeaders: Message[] = [
                {
                    value: Buffer.from('redirect'),
                    topic: 'test',
                    partition: 0,
                    offset: 1,
                    size: 8,
                    timestamp: 1234567891,
                    headers: [
                        { distinct_id: Buffer.from('user-456') },
                        { token: Buffer.from('redirect-token') },
                        { event: Buffer.from('$identify') },
                        { uuid: Buffer.from('redirect-uuid-456') },
                    ],
                },
            ]

            const batchResults: BatchPipelineResultWithContext<any> = [
                {
                    result: redirect('test redirect', 'overflow-topic', false, true),
                    context: { message: messagesWithHeaders[0] },
                },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([])
            expect(mockRedirectMessageToTopic).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockPromiseScheduler,
                messagesWithHeaders[0],
                'overflow-topic',
                'unknown',
                false,
                true
            )

            // Verify the message passed to redirect has the correct headers
            const calledMessage = (mockRedirectMessageToTopic as jest.Mock).mock.calls[0][2]
            expect(calledMessage.headers).toEqual([
                { distinct_id: Buffer.from('user-456') },
                { token: Buffer.from('redirect-token') },
                { event: Buffer.from('$identify') },
                { uuid: Buffer.from('redirect-uuid-456') },
            ])
        })

        it('should filter out dlq results and send to DLQ', async () => {
            const messages: Message[] = [
                { value: Buffer.from('test1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('dlq'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('test3'), topic: 'test', partition: 0, offset: 3 } as Message,
            ]

            const testError = new Error('test error')
            // Create batch results directly
            const batchResults: BatchPipelineResultWithContext<any> = [
                { result: ok({ processed: 'test1' }), context: { message: messages[0] } },
                { result: dlq('test dlq reason', testError), context: { message: messages[1] } },
                { result: ok({ processed: 'test3' }), context: { message: messages[2] } },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([{ processed: 'test1' }, { processed: 'test3' }])
            expect(mockSendMessageToDLQ).toHaveBeenCalledWith(
                mockKafkaProducer,
                messages[1],
                testError,
                'unknown',
                'test-dlq'
            )
        })

        it('should send DLQ messages with event and uuid headers', async () => {
            const messagesWithHeaders: Message[] = [
                {
                    value: Buffer.from('dlq'),
                    topic: 'test',
                    partition: 0,
                    offset: 1,
                    size: 3,
                    timestamp: 1234567890,
                    headers: [
                        { distinct_id: Buffer.from('user-123') },
                        { token: Buffer.from('test-token') },
                        { event: Buffer.from('$pageview') },
                        { uuid: Buffer.from('event-uuid-123') },
                    ],
                },
            ]

            const testError = new Error('test error')
            const batchResults: BatchPipelineResultWithContext<any> = [
                { result: dlq('test dlq reason', testError), context: { message: messagesWithHeaders[0] } },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([])
            expect(mockSendMessageToDLQ).toHaveBeenCalledWith(
                mockKafkaProducer,
                messagesWithHeaders[0],
                testError,
                'unknown',
                'test-dlq'
            )

            // Verify the message passed to DLQ has the correct headers
            const calledMessage = (mockSendMessageToDLQ as jest.Mock).mock.calls[0][1]
            expect(calledMessage.headers).toEqual([
                { distinct_id: Buffer.from('user-123') },
                { token: Buffer.from('test-token') },
                { event: Buffer.from('$pageview') },
                { uuid: Buffer.from('event-uuid-123') },
            ])
        })

        it('should handle dlq result without error and create default error', async () => {
            const messages: Message[] = [
                { value: Buffer.from('dlq'), topic: 'test', partition: 0, offset: 1 } as Message,
            ]

            // Create batch results directly
            const batchResults: BatchPipelineResultWithContext<any> = [
                { result: dlq('test dlq reason'), context: { message: messages[0] } },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([])
            expect(mockSendMessageToDLQ).toHaveBeenCalledWith(
                mockKafkaProducer,
                messages[0],
                expect.any(Error),
                'unknown',
                'test-dlq'
            )

            const errorArg = (mockSendMessageToDLQ as jest.Mock).mock.calls[0][2]
            expect(errorArg.message).toBe('test dlq reason')
        })

        it('should handle mixed results correctly', async () => {
            const messages: Message[] = [
                { value: Buffer.from('success1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('drop'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('success2'), topic: 'test', partition: 0, offset: 3 } as Message,
                { value: Buffer.from('redirect'), topic: 'test', partition: 0, offset: 4 } as Message,
                { value: Buffer.from('dlq'), topic: 'test', partition: 0, offset: 5 } as Message,
            ]

            // Create batch results directly
            const batchResults: BatchPipelineResultWithContext<any> = [
                { result: ok({ processed: 'success1' }), context: { message: messages[0] } },
                { result: drop('dropped item'), context: { message: messages[1] } },
                { result: ok({ processed: 'success2' }), context: { message: messages[2] } },
                { result: redirect('redirected item', 'overflow-topic'), context: { message: messages[3] } },
                { result: dlq('dlq item', new Error('processing error')), context: { message: messages[4] } },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([{ processed: 'success1' }, { processed: 'success2' }])

            // Verify all non-success results were handled
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(messages[1], 'dropped item', 'unknown')
            expect(mockRedirectMessageToTopic).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockPromiseScheduler,
                messages[3],
                'overflow-topic',
                'unknown',
                true,
                true
            )
            expect(mockSendMessageToDLQ).toHaveBeenCalledWith(
                mockKafkaProducer,
                messages[4],
                expect.any(Error),
                'unknown',
                'test-dlq'
            )
        })
    })

    describe('last step reporting', () => {
        it('should report last steps for all results including failed messages', async () => {
            const messages: Message[] = [
                { value: Buffer.from('success'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('drop'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('redirect'), topic: 'test', partition: 0, offset: 3 } as Message,
                { value: Buffer.from('dlq'), topic: 'test', partition: 0, offset: 4 } as Message,
            ]

            // Create batch results with different lastStep values
            const batchResults: BatchPipelineResultWithContext<any> = [
                { result: ok({ processed: 'success' }), context: { message: messages[0], lastStep: 'validationStep' } },
                { result: drop('dropped item'), context: { message: messages[1], lastStep: 'filterStep' } },
                {
                    result: redirect('redirected item', 'overflow-topic'),
                    context: { message: messages[2], lastStep: 'routingStep' },
                },
                {
                    result: dlq('dlq item', new Error('processing error')),
                    context: { message: messages[3], lastStep: 'processingStep' },
                },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([{ processed: 'success' }])

            // Verify all last steps were reported
            expect(mockPipelineLastStepCounter.labels).toHaveBeenCalledWith('validationStep')
            expect(mockPipelineLastStepCounter.labels).toHaveBeenCalledWith('filterStep')
            expect(mockPipelineLastStepCounter.labels).toHaveBeenCalledWith('routingStep')
            expect(mockPipelineLastStepCounter.labels).toHaveBeenCalledWith('processingStep')

            // Verify inc() was called for each step
            expect(mockPipelineLastStepCounter.labels().inc).toHaveBeenCalledTimes(4)
        })

        it('should not report last step when context has no lastStep', async () => {
            const messages: Message[] = [
                { value: Buffer.from('success'), topic: 'test', partition: 0, offset: 1 } as Message,
            ]

            // Create batch results without lastStep
            const batchResults: BatchPipelineResultWithContext<any> = [
                { result: ok({ processed: 'success' }), context: { message: messages[0] } },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([{ processed: 'success' }])

            // Verify no last step was reported
            expect(mockPipelineLastStepCounter.labels).not.toHaveBeenCalled()
        })
    })

    describe('concurrent processing', () => {
        it('should handle concurrent processing results', async () => {
            const messages: Message[] = [
                { value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('2'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('3'), topic: 'test', partition: 0, offset: 3 } as Message,
            ]

            // Create batch results directly
            const batchResults: BatchPipelineResultWithContext<any> = [
                { result: ok({ count: 2 }), context: { message: messages[0] } },
                { result: ok({ count: 4 }), context: { message: messages[1] } },
                { result: ok({ count: 6 }), context: { message: messages[2] } },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([{ count: 2 }, { count: 4 }, { count: 6 }])
        })
    })

    describe('redirect result with default parameters', () => {
        it('should use default preserveKey and awaitAck when not specified', async () => {
            const messages: Message[] = [
                { value: Buffer.from('redirect'), topic: 'test', partition: 0, offset: 1 } as Message,
            ]

            // Create batch results directly
            const batchResults: BatchPipelineResultWithContext<any> = [
                { result: redirect('test redirect', 'overflow-topic'), context: { message: messages[0] } },
            ]

            const pipeline = createNewBatchPipeline()
            const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
            resultPipeline.feed(batchResults)
            const results = await resultPipeline.next()

            expect(results).toEqual([])
            expect(mockRedirectMessageToTopic).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockPromiseScheduler,
                messages[0],
                'overflow-topic',
                'unknown',
                true, // default preserveKey
                true // default awaitAck
            )
        })
    })
})

describe('Integration tests', () => {
    let mockKafkaProducer: KafkaProducerWrapper
    let mockPromiseScheduler: PromiseScheduler
    let config: PipelineConfig

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            producer: {} as any,
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockPromiseScheduler = {
            schedule: jest.fn(),
        } as unknown as PromiseScheduler

        config = {
            kafkaProducer: mockKafkaProducer,
            dlqTopic: 'test-dlq',
            promiseScheduler: mockPromiseScheduler,
        }
    })

    it('should handle realistic event processing pipeline', async () => {
        const messages: Message[] = [
            { value: Buffer.from('test-event'), topic: 'test', partition: 0, offset: 1 } as Message,
        ]

        // Create batch results directly
        const batchResults: BatchPipelineResultWithContext<any> = [
            {
                result: ok({
                    eventType: 'pageview',
                    userId: 'user123',
                    isValid: true,
                    timestamp: '2023-01-01T00:00:00Z',
                }),
                context: { message: messages[0] },
            },
        ]

        const pipeline = createNewBatchPipeline()
        const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
        resultPipeline.feed(batchResults)
        const results = await resultPipeline.next()

        expect(results).toEqual([
            {
                eventType: 'pageview',
                userId: 'user123',
                isValid: true,
                timestamp: '2023-01-01T00:00:00Z',
            },
        ])
    })

    it('should handle pipeline failure at different stages', async () => {
        const messages: Message[] = [{ value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message]

        // Create batch results directly
        const batchResults: BatchPipelineResultWithContext<any> = [
            { result: dlq('Validation failed', new Error('Invalid data')), context: { message: messages[0] } },
        ]

        const pipeline = createNewBatchPipeline()
        const resultPipeline = ResultHandlingPipeline.of(pipeline, config)
        resultPipeline.feed(batchResults)
        const results = await resultPipeline.next()

        expect(results).toEqual([])
        expect(mockSendMessageToDLQ).toHaveBeenCalledWith(
            mockKafkaProducer,
            messages[0],
            expect.any(Error),
            'unknown',
            'test-dlq'
        )
    })
})
