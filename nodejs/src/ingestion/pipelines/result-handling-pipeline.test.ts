import { Message } from 'node-rdkafka'

import { createMockPipeline } from '../../../tests/helpers/mock-pipeline'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { ingestionPipelineResultCounter } from '../../worker/ingestion/event-pipeline/metrics'
import {
    logDroppedMessage,
    produceMessageToDLQ,
    redirectMessageToOutput,
} from '../../worker/ingestion/pipeline-helpers'
import { DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT, OVERFLOW_OUTPUT } from '../common/outputs'
import { OverflowOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createContext } from './helpers'
import { PipelineConfig, ResultHandlingPipeline } from './result-handling-pipeline'
import { dlq, drop, ok, redirect } from './results'

// Mock the pipeline helpers
jest.mock('../../worker/ingestion/pipeline-helpers', () => ({
    logDroppedMessage: jest.fn(),
    redirectMessageToOutput: jest.fn(),
    produceMessageToDLQ: jest.fn(),
}))

// Mock the metrics
jest.mock('../../worker/ingestion/event-pipeline/metrics', () => ({
    ingestionPipelineResultCounter: {
        labels: jest.fn().mockReturnValue({
            inc: jest.fn(),
        }),
    },
}))

const mockLogDroppedMessage = logDroppedMessage as jest.MockedFunction<typeof logDroppedMessage>
const mockRedirectMessageToOutput = redirectMessageToOutput as jest.MockedFunction<typeof redirectMessageToOutput>
const mockProduceMessageToDLQ = produceMessageToDLQ as jest.MockedFunction<typeof produceMessageToDLQ>
const mockIngestionPipelineResultCounter = ingestionPipelineResultCounter as jest.Mocked<
    typeof ingestionPipelineResultCounter
>

describe('ResultHandlingPipeline', () => {
    let mockDlqProducer: KafkaProducerWrapper
    let mockRedirectProducer: KafkaProducerWrapper
    let mockIngestionWarningsProducer: KafkaProducerWrapper
    let mockPromiseScheduler: PromiseScheduler
    let config: PipelineConfig<OverflowOutput>

    beforeEach(() => {
        jest.clearAllMocks()

        mockDlqProducer = {
            producer: {} as any,
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockRedirectProducer = {
            producer: {} as any,
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockIngestionWarningsProducer = {
            producer: {} as any,
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockPromiseScheduler = {
            schedule: jest.fn(),
        } as unknown as PromiseScheduler

        config = {
            outputs: new IngestionOutputs({
                [DLQ_OUTPUT]: { topic: 'test-dlq', producer: mockDlqProducer },
                [OVERFLOW_OUTPUT]: { topic: 'overflow-topic', producer: mockRedirectProducer },
                [INGESTION_WARNINGS_OUTPUT]: {
                    topic: 'ingestion_warnings_test',
                    producer: mockIngestionWarningsProducer,
                },
            }),
            promiseScheduler: mockPromiseScheduler,
        }
    })

    describe('basic functionality', () => {
        it('should process successful results and return batch pipeline results', async () => {
            const messages: Message[] = [
                { value: Buffer.from('test1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('test2'), topic: 'test', partition: 0, offset: 2 } as Message,
            ]

            // Create batch results directly
            const batchResults = [
                createContext(ok({ processed: 'test1', message: messages[0] }), { message: messages[0] }),
                createContext(ok({ processed: 'test2', message: messages[1] }), { message: messages[1] }),
            ]

            const mockPipeline = createMockPipeline(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            expect(results).not.toBeNull()
            expect(results).toEqual([
                createContext(ok({ processed: 'test1', message: messages[0] }), { message: messages[0] }),
                createContext(ok({ processed: 'test2', message: messages[1] }), { message: messages[1] }),
            ])
        })

        it('should handle empty batch', async () => {
            const mockPipeline = createMockPipeline([])
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            expect(results).toBeNull()
        })
    })

    describe('result handling', () => {
        it('should handle dropped results and log them', async () => {
            const messages: Message[] = [
                { value: Buffer.from('test1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('drop'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('test3'), topic: 'test', partition: 0, offset: 3 } as Message,
            ]

            // Create batch results directly
            const batchResults = [
                createContext(ok({ processed: 'test1' }), { message: messages[0] }),
                createContext(drop('test drop reason'), { message: messages[1] }),
                createContext(ok({ processed: 'test3' }), { message: messages[2] }),
            ]

            const mockPipeline = createMockPipeline(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            expect(results).not.toBeNull()
            expect(results).toEqual([
                createContext(ok({ processed: 'test1' }), { message: messages[0] }),
                createContext(drop('test drop reason'), { message: messages[1] }),
                createContext(ok({ processed: 'test3' }), { message: messages[2] }),
            ])
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(messages[1], 'test drop reason', 'unknown')
        })

        it('should handle redirected results and add side effects', async () => {
            mockRedirectMessageToOutput.mockResolvedValue(undefined)

            const messages: Message[] = [
                { value: Buffer.from('test1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('redirect'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('test3'), topic: 'test', partition: 0, offset: 3 } as Message,
            ]

            // Create batch results directly
            const batchResults = [
                createContext(ok({ processed: 'test1' }), { message: messages[0] }),
                createContext(redirect('test redirect', OVERFLOW_OUTPUT, true, false), { message: messages[1] }),
                createContext(ok({ processed: 'test3' }), { message: messages[2] }),
            ]

            const mockPipeline = createMockPipeline<any, { message: Message }, OverflowOutput>(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            // Should return all results including redirect result with side effects
            expect(results).not.toBeNull()
            expect(results).toHaveLength(3)
            expect(results![0]).toEqual(createContext(ok({ processed: 'test1' }), { message: messages[0] }))
            expect(results![1].result).toEqual(redirect('test redirect', OVERFLOW_OUTPUT, true, false))
            expect(results![1].context.sideEffects).toHaveLength(1)
            expect(results![2]).toEqual(createContext(ok({ processed: 'test3' }), { message: messages[2] }))

            // Extract and await side effects
            const sideEffects = results![1].context.sideEffects
            await Promise.all(sideEffects)

            // Now verify the mock was called
            expect(mockRedirectMessageToOutput).toHaveBeenCalledWith(
                config.outputs,
                OVERFLOW_OUTPUT,
                mockPromiseScheduler,
                messages[1],
                'unknown',
                true,
                false
            )
        })

        it('should redirect messages with event and uuid headers', async () => {
            mockRedirectMessageToOutput.mockResolvedValue(undefined)

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

            const batchResults = [
                createContext(redirect('test redirect', OVERFLOW_OUTPUT, false, true), {
                    message: messagesWithHeaders[0],
                }),
            ]

            const mockPipeline = createMockPipeline<any, { message: Message }, OverflowOutput>(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            // Should return the redirect result with side effects
            expect(results).not.toBeNull()
            expect(results).toHaveLength(1)
            expect(results![0].result).toEqual(redirect('test redirect', OVERFLOW_OUTPUT, false, true))
            expect(results![0].context.sideEffects).toHaveLength(1)

            // Extract and await side effects
            const sideEffects = results![0].context.sideEffects
            await Promise.all(sideEffects)

            // Now verify the mock was called
            expect(mockRedirectMessageToOutput).toHaveBeenCalledWith(
                config.outputs,
                OVERFLOW_OUTPUT,
                mockPromiseScheduler,
                messagesWithHeaders[0],
                'unknown',
                false,
                true
            )

            // Verify the message passed to redirect has the correct headers
            const calledMessage = (mockRedirectMessageToOutput as jest.Mock).mock.calls[0][3]
            expect(calledMessage.headers).toEqual([
                { distinct_id: Buffer.from('user-456') },
                { token: Buffer.from('redirect-token') },
                { event: Buffer.from('$identify') },
                { uuid: Buffer.from('redirect-uuid-456') },
            ])
        })

        it('should handle dlq results and add side effects', async () => {
            mockProduceMessageToDLQ.mockResolvedValue(undefined)

            const messages: Message[] = [
                { value: Buffer.from('test1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('dlq'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('test3'), topic: 'test', partition: 0, offset: 3 } as Message,
            ]

            const testError = new Error('test error')
            // Create batch results directly
            const batchResults = [
                createContext(ok({ processed: 'test1' }), { message: messages[0] }),
                createContext(dlq('test dlq reason', testError), { message: messages[1] }),
                createContext(ok({ processed: 'test3' }), { message: messages[2] }),
            ]

            const mockPipeline = createMockPipeline(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            // Should return all results including dlq result with side effects
            expect(results).not.toBeNull()
            expect(results).toHaveLength(3)
            expect(results![0]).toEqual(createContext(ok({ processed: 'test1' }), { message: messages[0] }))
            expect(results![1].result).toEqual(dlq('test dlq reason', testError))
            expect(results![1].context.sideEffects).toHaveLength(1)
            expect(results![2]).toEqual(createContext(ok({ processed: 'test3' }), { message: messages[2] }))

            // Extract and await side effects
            const sideEffects = results![1].context.sideEffects
            await Promise.all(sideEffects)

            // Now verify the mock was called
            expect(mockProduceMessageToDLQ).toHaveBeenCalledWith(config.outputs, messages[1], testError, 'unknown')
        })

        it('should send DLQ messages with event and uuid headers', async () => {
            mockProduceMessageToDLQ.mockResolvedValue(undefined)

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
            const batchResults = [createContext(dlq('test dlq reason', testError), { message: messagesWithHeaders[0] })]

            const mockPipeline = createMockPipeline(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            // Should return the dlq result with side effects
            expect(results).not.toBeNull()
            expect(results).toHaveLength(1)
            expect(results![0].result).toEqual(dlq('test dlq reason', testError))
            expect(results![0].context.sideEffects).toHaveLength(1)

            // Extract and await side effects
            const sideEffects = results![0].context.sideEffects
            await Promise.all(sideEffects)

            // Now verify the mock was called
            expect(mockProduceMessageToDLQ).toHaveBeenCalledWith(
                config.outputs,
                messagesWithHeaders[0],
                testError,
                'unknown'
            )

            // Verify the message passed to DLQ has the correct headers
            const calledMessage = (mockProduceMessageToDLQ as jest.Mock).mock.calls[0][1]
            expect(calledMessage.headers).toEqual([
                { distinct_id: Buffer.from('user-123') },
                { token: Buffer.from('test-token') },
                { event: Buffer.from('$pageview') },
                { uuid: Buffer.from('event-uuid-123') },
            ])
        })

        it('should handle dlq result without error and create default error', async () => {
            mockProduceMessageToDLQ.mockResolvedValue(undefined)

            const messages: Message[] = [
                { value: Buffer.from('dlq'), topic: 'test', partition: 0, offset: 1 } as Message,
            ]

            // Create batch results directly
            const batchResults = [createContext(dlq('test dlq reason'), { message: messages[0] })]

            const mockPipeline = createMockPipeline(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            // Should return the dlq result with side effects
            expect(results).not.toBeNull()
            expect(results).toHaveLength(1)
            expect(results![0].result).toEqual(dlq('test dlq reason'))
            expect(results![0].context.sideEffects).toHaveLength(1)

            // Extract and await side effects
            const sideEffects = results![0].context.sideEffects
            await Promise.all(sideEffects)

            // Now verify the mock was called
            expect(mockProduceMessageToDLQ).toHaveBeenCalledWith(
                config.outputs,
                messages[0],
                expect.any(Error),
                'unknown'
            )

            const errorArg = (mockProduceMessageToDLQ as jest.Mock).mock.calls[0][2]
            expect(errorArg.message).toBe('test dlq reason')
        })

        it('should handle mixed results correctly', async () => {
            mockRedirectMessageToOutput.mockResolvedValue(undefined)
            mockProduceMessageToDLQ.mockResolvedValue(undefined)

            const messages: Message[] = [
                { value: Buffer.from('success1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('drop'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('success2'), topic: 'test', partition: 0, offset: 3 } as Message,
                { value: Buffer.from('redirect'), topic: 'test', partition: 0, offset: 4 } as Message,
                { value: Buffer.from('dlq'), topic: 'test', partition: 0, offset: 5 } as Message,
            ]

            // Create batch results directly
            const batchResults = [
                createContext(ok({ processed: 'success1' }), { message: messages[0] }),
                createContext(drop('dropped item'), { message: messages[1] }),
                createContext(ok({ processed: 'success2' }), { message: messages[2] }),
                createContext(redirect('redirected item', OVERFLOW_OUTPUT), { message: messages[3] }),
                createContext(dlq('dlq item', new Error('processing error')), { message: messages[4] }),
            ]

            const mockPipeline = createMockPipeline<any, { message: Message }, OverflowOutput>(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            // Should return all results including non-success ones
            expect(results).not.toBeNull()
            expect(results).toHaveLength(5)
            expect(results![0]).toEqual(createContext(ok({ processed: 'success1' }), { message: messages[0] }))
            expect(results![1]).toEqual(createContext(drop('dropped item'), { message: messages[1] }))
            expect(results![2]).toEqual(createContext(ok({ processed: 'success2' }), { message: messages[2] }))
            expect(results![3].result).toEqual(redirect('redirected item', OVERFLOW_OUTPUT))
            expect(results![3].context.sideEffects).toHaveLength(1)
            expect(results![4].result).toEqual(dlq('dlq item', new Error('processing error')))
            expect(results![4].context.sideEffects).toHaveLength(1)

            // Extract and await side effects from redirect and dlq results
            const redirectSideEffects = results![3].context.sideEffects
            const dlqSideEffects = results![4].context.sideEffects
            await Promise.all([...redirectSideEffects, ...dlqSideEffects])

            // Verify all non-success results were handled
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(messages[1], 'dropped item', 'unknown')
            expect(mockRedirectMessageToOutput).toHaveBeenCalledWith(
                config.outputs,
                OVERFLOW_OUTPUT,
                mockPromiseScheduler,
                messages[3],
                'unknown',
                true,
                true
            )
            expect(mockProduceMessageToDLQ).toHaveBeenCalledWith(
                config.outputs,
                messages[4],
                expect.any(Error),
                'unknown'
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
            const batchResults = [
                createContext(ok({ processed: 'success' }), { message: messages[0], lastStep: 'validationStep' }),
                createContext(drop('dropped item'), { message: messages[1], lastStep: 'filterStep' }),
                createContext(redirect('redirected item', OVERFLOW_OUTPUT), {
                    message: messages[2],
                    lastStep: 'routingStep',
                }),
                createContext(dlq('dlq item', new Error('processing error')), {
                    message: messages[3],
                    lastStep: 'processingStep',
                }),
            ]

            const mockPipeline = createMockPipeline<any, { message: Message }, OverflowOutput>(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            // Should return all results including non-success ones
            expect(results).not.toBeNull()
            expect(results).toHaveLength(4)

            // Verify all results were recorded with correct step names
            expect(mockIngestionPipelineResultCounter.labels).toHaveBeenCalledWith({
                result: 'ok',
                last_step_name: 'validationStep',
                details: '',
            })
            expect(mockIngestionPipelineResultCounter.labels).toHaveBeenCalledWith({
                result: 'drop',
                last_step_name: 'filterStep',
                details: 'dropped item',
            })
            expect(mockIngestionPipelineResultCounter.labels).toHaveBeenCalledWith({
                result: 'redirect',
                last_step_name: 'routingStep',
                details: 'overflow(preserve_key=true)',
            })
            expect(mockIngestionPipelineResultCounter.labels).toHaveBeenCalledWith({
                result: 'dlq',
                last_step_name: 'processingStep',
                details: 'dlq item',
            })
        })

        it('should not report last step when context has no lastStep', async () => {
            const messages: Message[] = [
                { value: Buffer.from('success'), topic: 'test', partition: 0, offset: 1 } as Message,
            ]

            // Create batch results without lastStep
            const batchResults = [createContext(ok({ processed: 'success' }), { message: messages[0] })]

            const mockPipeline = createMockPipeline(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            expect(results).not.toBeNull()
            expect(results).toEqual([createContext(ok({ processed: 'success' }), { message: messages[0] })])

            // Verify result was recorded with 'unknown' step name
            expect(mockIngestionPipelineResultCounter.labels).toHaveBeenCalledWith({
                result: 'ok',
                last_step_name: 'unknown',
                details: '',
            })
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
            const batchResults = [
                createContext(ok({ count: 2 }), { message: messages[0] }),
                createContext(ok({ count: 4 }), { message: messages[1] }),
                createContext(ok({ count: 6 }), { message: messages[2] }),
            ]

            const mockPipeline = createMockPipeline(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            expect(results).not.toBeNull()
            expect(results).toEqual([
                createContext(ok({ count: 2 }), { message: messages[0] }),
                createContext(ok({ count: 4 }), { message: messages[1] }),
                createContext(ok({ count: 6 }), { message: messages[2] }),
            ])
        })
    })

    describe('redirect result with default parameters', () => {
        it('should use default preserveKey and awaitAck when not specified', async () => {
            mockRedirectMessageToOutput.mockResolvedValue(undefined)

            const messages: Message[] = [
                { value: Buffer.from('redirect'), topic: 'test', partition: 0, offset: 1 } as Message,
            ]

            // Create batch results directly
            const batchResults = [createContext(redirect('test redirect', OVERFLOW_OUTPUT), { message: messages[0] })]

            const mockPipeline = createMockPipeline<any, { message: Message }, OverflowOutput>(batchResults)
            const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
            const results = await resultPipeline.next()

            // Should return the redirect result with side effects
            expect(results).not.toBeNull()
            expect(results).toHaveLength(1)
            expect(results![0].result).toEqual(redirect('test redirect', OVERFLOW_OUTPUT))
            expect(results![0].context.sideEffects).toHaveLength(1)

            // Extract and await side effects
            const sideEffects = results![0].context.sideEffects
            await Promise.all(sideEffects)

            // Now verify the mock was called with default parameters
            expect(mockRedirectMessageToOutput).toHaveBeenCalledWith(
                config.outputs,
                OVERFLOW_OUTPUT,
                mockPromiseScheduler,
                messages[0],
                'unknown',
                true, // default preserveKey
                true // default awaitAck
            )
        })
    })
})

describe('Integration tests', () => {
    let mockDlqProducer: KafkaProducerWrapper
    let mockRedirectProducer: KafkaProducerWrapper
    let mockIngestionWarningsProducer: KafkaProducerWrapper
    let mockPromiseScheduler: PromiseScheduler
    let config: PipelineConfig<OverflowOutput>

    beforeEach(() => {
        jest.clearAllMocks()

        mockDlqProducer = {
            producer: {} as any,
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockRedirectProducer = {
            producer: {} as any,
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockIngestionWarningsProducer = {
            producer: {} as any,
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockPromiseScheduler = {
            schedule: jest.fn(),
        } as unknown as PromiseScheduler

        config = {
            outputs: new IngestionOutputs({
                [DLQ_OUTPUT]: { topic: 'test-dlq', producer: mockDlqProducer },
                [OVERFLOW_OUTPUT]: { topic: 'overflow-topic', producer: mockRedirectProducer },
                [INGESTION_WARNINGS_OUTPUT]: {
                    topic: 'ingestion_warnings_test',
                    producer: mockIngestionWarningsProducer,
                },
            }),
            promiseScheduler: mockPromiseScheduler,
        }
    })

    it('should handle realistic event processing pipeline', async () => {
        const messages: Message[] = [
            { value: Buffer.from('test-event'), topic: 'test', partition: 0, offset: 1 } as Message,
        ]

        // Create batch results directly
        const batchResults = [
            createContext(
                ok({
                    eventType: 'pageview',
                    userId: 'user123',
                    isValid: true,
                    timestamp: '2023-01-01T00:00:00Z',
                }),
                { message: messages[0] }
            ),
        ]

        const mockPipeline = createMockPipeline(batchResults)
        const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
        const results = await resultPipeline.next()

        expect(results).toEqual([
            createContext(
                ok({
                    eventType: 'pageview',
                    userId: 'user123',
                    isValid: true,
                    timestamp: '2023-01-01T00:00:00Z',
                }),
                { message: messages[0] }
            ),
        ])
    })

    it('should handle pipeline failure at different stages', async () => {
        const messages: Message[] = [{ value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message]

        // Create batch results directly
        const batchResults = [
            createContext(dlq('Validation failed', new Error('Invalid data')), { message: messages[0] }),
        ]

        const mockPipeline = createMockPipeline(batchResults)
        const resultPipeline = new ResultHandlingPipeline(mockPipeline, config)
        const results = await resultPipeline.next()

        // Should return the DLQ result with side effects
        expect(results).toEqual([
            createContext(dlq('Validation failed', new Error('Invalid data')), {
                message: messages[0],
                sideEffects: expect.arrayContaining([expect.any(Promise)]),
            }),
        ])

        // Await the side effects to trigger the DLQ operation
        if (results && results.length > 0) {
            const sideEffects = results[0].context.sideEffects
            await Promise.all(sideEffects)
        }

        expect(mockProduceMessageToDLQ).toHaveBeenCalledWith(config.outputs, messages[0], expect.any(Error), 'unknown')
    })
})
