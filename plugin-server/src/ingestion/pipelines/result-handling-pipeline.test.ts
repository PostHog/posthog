import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { PromiseScheduler } from '../../utils/promise-scheduler'
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

const mockLogDroppedMessage = logDroppedMessage as jest.MockedFunction<typeof logDroppedMessage>
const mockRedirectMessageToTopic = redirectMessageToTopic as jest.MockedFunction<typeof redirectMessageToTopic>
const mockSendMessageToDLQ = sendMessageToDLQ as jest.MockedFunction<typeof sendMessageToDLQ>

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
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(messages[1], 'test drop reason', 'result_handler')
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
                'result_handler',
                true,
                false
            )
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
                'result_handler',
                'test-dlq'
            )
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
                'result_handler',
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
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(messages[1], 'dropped item', 'result_handler')
            expect(mockRedirectMessageToTopic).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockPromiseScheduler,
                messages[3],
                'overflow-topic',
                'result_handler',
                true,
                true
            )
            expect(mockSendMessageToDLQ).toHaveBeenCalledWith(
                mockKafkaProducer,
                messages[4],
                expect.any(Error),
                'result_handler',
                'test-dlq'
            )
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
                'result_handler',
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
            'result_handler',
            'test-dlq'
        )
    })
})
