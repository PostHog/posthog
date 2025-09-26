import { Message } from 'node-rdkafka'

import { createBatch, createNewBatchPipeline, createNewPipeline } from './helpers'
import { PipelineConfig, ResultHandlingPipeline } from './result-handling-pipeline'
import { PipelineResult, dlq, drop, ok, redirect } from './results'
import { BatchProcessingStep, SequentialBatchPipeline } from './sequential-batch-pipeline'
import { AsyncProcessingStep, SyncProcessingStep } from './steps'

// Simple test types - only include fields needed for testing
type TestTeam = {
    id: number
    name: string
}

type TestEvent = {
    uuid: string
    event: string
    token: string
    batch_result?: string // Optional field added by batch processing
}

type TestHeaders = {
    token: string
}

type TestEventWithTeam = {
    message: Message
    event: TestEvent
    team: TestTeam
    headers: TestHeaders
}

/**
 * Integration tests for the pipeline system that approximate the preprocessing pipeline
 * structure used in the ingestion consumer. These tests mirror the key aspects of the
 * ingestion pipeline but are not an exact replica - they focus on testing the core
 * pipeline behavior, ordering guarantees, and result handling patterns.
 *
 * Note: Adding more than 3 preprocessing steps doesn't add meaningful test coverage
 * since the tests already verify the essential pipeline patterns (sync steps, async steps,
 * batch processing, result handling). The goal is to test pipeline behavior, not to
 * replicate every single step from the actual ingestion consumer.
 */

// Helper function to create Jest mocks for pipeline steps
const createMockStep = <TInput extends { message: Message }, TOutput>(
    resultMap: Map<string, PipelineResult<TOutput>>
): jest.MockedFunction<SyncProcessingStep<TInput, TOutput>> => {
    return jest.fn((input: TInput) => {
        // Extract event ID from message value
        const eventId = input.message.value?.toString() || 'default'

        const result = resultMap.get(eventId)

        if (result) {
            return result
        }

        // Throw exception if no result found in map
        throw new Error(`No result found for event ID: ${eventId}`)
    })
}

type AsyncStepConfig<TOutput> = {
    delay: number
    result: PipelineResult<TOutput>
}

const createMockAsyncStep = <TInput extends { message: Message }, TOutput>(
    resultMap: Map<string, AsyncStepConfig<TOutput>>
): jest.MockedFunction<AsyncProcessingStep<TInput, TOutput>> => {
    return jest.fn(async (input: TInput) => {
        // Extract event ID from message value
        const eventId = input.message.value?.toString() || 'default'

        const config = resultMap.get(eventId)

        if (config) {
            // Simulate async work with configurable delay
            await new Promise((resolve) => setTimeout(resolve, config.delay))
            return config.result
        }

        // Throw exception if no result found in map
        throw new Error(`No result found for event ID: ${eventId}`)
    })
}

const createMockBatchStep = <TInput, TOutput>(
    resultMap: Map<number, PipelineResult<TOutput>>
): jest.MockedFunction<BatchProcessingStep<TInput, TOutput>> => {
    return jest.fn(async (events: TInput[]): Promise<PipelineResult<TOutput>[]> => {
        await new Promise((resolve) => setTimeout(resolve, 1)) // Simulate async work
        return events.map((_, index) => {
            const result = resultMap.get(index)
            if (result) {
                return result
            }
            // Throw exception if no result found in map
            throw new Error(`No result found for event index: ${index}`)
        })
    })
}

describe('Pipeline Integration Tests', () => {
    let mockKafkaProducer: any
    let mockPromiseScheduler: any
    let pipelineConfig: PipelineConfig

    beforeEach(() => {
        mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        }

        mockPromiseScheduler = {
            schedule: jest.fn(),
        }

        pipelineConfig = {
            kafkaProducer: mockKafkaProducer,
            dlqTopic: 'test-dlq-topic',
            promiseScheduler: mockPromiseScheduler,
        }
    })

    describe('Pipeline Integration Scenarios', () => {
        it('should process events successfully through the pipeline', async () => {
            const messages: Message[] = [
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    value: Buffer.from('event1'),
                    timestamp: Date.now(),
                } as Message,
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 2,
                    key: Buffer.from('key2'),
                    value: Buffer.from('event2'),
                    timestamp: Date.now() + 1,
                } as Message,
            ]

            // Define result maps
            const step1Map = new Map<string, PipelineResult<{ message: Message; headers: TestHeaders }>>([
                ['event1', ok({ message: messages[0], headers: { token: 'test-token' } })],
                ['event2', ok({ message: messages[1], headers: { token: 'test-token' } })],
            ])
            const step2Map = new Map<
                string,
                PipelineResult<{ message: Message; headers: TestHeaders; event: TestEvent }>
            >([
                [
                    'event1',
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event1', event: 'test-event', token: 'test-token' },
                    }),
                ],
                [
                    'event2',
                    ok({
                        message: messages[1],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event2', event: 'test-event', token: 'test-token' },
                    }),
                ],
            ])
            const asyncStep3Map = new Map<string, AsyncStepConfig<TestEventWithTeam>>([
                [
                    'event1',
                    {
                        delay: 10,
                        result: ok({
                            message: messages[0],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event1', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
                [
                    'event2',
                    {
                        delay: 10,
                        result: ok({
                            message: messages[1],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event2', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
            ])

            // Define batch step result map
            const batchStep4Map = new Map<number, PipelineResult<TestEventWithTeam>>([
                [
                    0,
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: {
                            uuid: 'event1',
                            event: 'test-event-0',
                            token: 'test-token',
                            batch_result: 'processed',
                        },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    1,
                    ok({
                        message: messages[1],
                        headers: { token: 'test-token' },
                        event: {
                            uuid: 'event2',
                            event: 'test-event-1',
                            token: 'test-token',
                            batch_result: 'processed',
                        },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
            ])

            // Define steps
            const step1 = createMockStep<{ message: Message }, { message: Message; headers: TestHeaders }>(step1Map)
            const step2 = createMockStep<
                { message: Message; headers: TestHeaders },
                { message: Message; headers: TestHeaders; event: TestEvent }
            >(step2Map)
            const asyncStep3 = createMockAsyncStep<
                { message: Message; headers: TestHeaders; event: TestEvent },
                TestEventWithTeam
            >(asyncStep3Map)

            // Define batch step
            const batchStep4 = createMockBatchStep<TestEventWithTeam, TestEventWithTeam>(batchStep4Map)

            // Create pipeline
            const preprocessingPipeline = createNewPipeline().pipe(step1).pipe(step2).pipeAsync(asyncStep3)

            const batchPipeline = createNewBatchPipeline()
                .pipeConcurrently(preprocessingPipeline)
                .gather()
                .pipeBatch(batchStep4)

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, pipelineConfig)

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            const results = await resultHandlingPipeline.next()

            expect(results).toHaveLength(2)
            expect((results![0] as TestEventWithTeam).event.event).toBe('test-event-0')
            expect((results![1] as TestEventWithTeam).event.event).toBe('test-event-1')

            // Verify batch step added processing metadata
            expect((results![0] as TestEventWithTeam).event.batch_result).toBe('processed')
            expect((results![1] as TestEventWithTeam).event.batch_result).toBe('processed')

            // Verify mock steps were called with correct arguments
            expect(step1).toHaveBeenCalledTimes(2)
            expect(step2).toHaveBeenCalledTimes(2)
            expect(asyncStep3).toHaveBeenCalledTimes(2)

            // Verify batch step was called with events in correct order
            expect(batchStep4).toHaveBeenCalledTimes(1)
            expect(batchStep4).toHaveBeenNthCalledWith(
                1,
                expect.arrayContaining([
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event1' }) }),
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event2' }) }),
                ])
            )
        })

        it('should handle events that are dropped', async () => {
            const messages: Message[] = [
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    value: Buffer.from('drop-event'),
                    timestamp: Date.now(),
                } as Message,
            ]

            // Define result map
            const step1Map = new Map<string, PipelineResult<{ message: Message; headers: TestHeaders }>>([
                ['drop-event', drop('Mock drop')],
            ])

            // Define step
            const step1 = createMockStep<{ message: Message }, { message: Message; headers: TestHeaders }>(step1Map)

            // Define batch step result map
            const batchStep2Map = new Map<number, PipelineResult<TestEventWithTeam>>([
                [
                    0,
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: { uuid: 'drop-event', event: 'test-event', token: 'test-token' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
            ])

            // Define batch step
            const batchStep2 = createMockBatchStep<{ message: Message; headers: TestHeaders }, TestEventWithTeam>(
                batchStep2Map
            )

            // Create pipeline
            const preprocessingPipeline = createNewPipeline().pipe(step1)

            const batchPipeline = createNewBatchPipeline()
                .pipeConcurrently(preprocessingPipeline)
                .gather()
                .pipeBatch(batchStep2)

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, pipelineConfig)

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            const results = await resultHandlingPipeline.next()

            // Should return empty array since event was dropped
            expect(results).toHaveLength(0)

            // Verify mock step was called with correct arguments
            expect(step1).toHaveBeenCalledTimes(1)
            expect(step1).toHaveBeenCalledWith({ message: messages[0] })
        })

        it('should handle events that are redirected', async () => {
            const messages: Message[] = [
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    value: Buffer.from('redirect-event'),
                    timestamp: Date.now(),
                } as Message,
            ]

            // Define result map
            const step1Map = new Map<string, PipelineResult<{ message: Message; headers: TestHeaders }>>([
                ['redirect-event', redirect('Mock redirect', 'mock-topic', true)],
            ])

            // Define step
            const step1 = createMockStep<{ message: Message }, { message: Message; headers: TestHeaders }>(step1Map)

            // Define batch step result map
            const batchStep2Map = new Map<number, PipelineResult<TestEventWithTeam>>([
                [
                    0,
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: { uuid: 'redirect-event', event: 'test-event', token: 'test-token' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
            ])

            // Define batch step
            const batchStep2 = createMockBatchStep<{ message: Message; headers: TestHeaders }, TestEventWithTeam>(
                batchStep2Map
            )

            // Create pipeline
            const preprocessingPipeline = createNewPipeline().pipe(step1)

            const batchPipeline = createNewBatchPipeline()
                .pipeConcurrently(preprocessingPipeline)
                .gather()
                .pipeBatch(batchStep2)

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, pipelineConfig)

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            const results = await resultHandlingPipeline.next()

            // Should return empty array since event was redirected
            expect(results).toHaveLength(0)
            expect(mockKafkaProducer.produce).toHaveBeenCalledWith(
                expect.objectContaining({
                    topic: 'mock-topic',
                    value: messages[0].value,
                    key: messages[0].key,
                })
            )

            // Verify mock step was called with correct arguments
            expect(step1).toHaveBeenCalledTimes(1)
            expect(step1).toHaveBeenCalledWith({ message: messages[0] })
        })

        it('should handle events that go to DLQ', async () => {
            const messages: Message[] = [
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    value: Buffer.from('dlq-event'),
                    timestamp: Date.now(),
                } as Message,
            ]

            // Define result map
            const step1Map = new Map<
                string,
                PipelineResult<{ message: Message; headers: TestHeaders; event: TestEvent }>
            >([['dlq-event', dlq('Mock DLQ', new Error('Mock error'))]])

            // Define step
            const step1 = createMockStep<
                { message: Message },
                { message: Message; headers: TestHeaders; event: TestEvent }
            >(step1Map)

            // Define batch step result map
            const batchStep2Map = new Map<number, PipelineResult<TestEventWithTeam>>([
                [
                    0,
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: { uuid: 'dlq-event', event: 'test-event', token: 'test-token' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
            ])

            // Define batch step
            const batchStep2 = createMockBatchStep<
                { message: Message; headers: TestHeaders; event: TestEvent },
                TestEventWithTeam
            >(batchStep2Map)

            // Create pipeline
            const preprocessingPipeline = createNewPipeline().pipe(step1)

            const batchPipeline = createNewBatchPipeline()
                .pipeConcurrently(preprocessingPipeline)
                .gather()
                .pipeBatch(batchStep2)

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, pipelineConfig)

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            const results = await resultHandlingPipeline.next()

            // Should return empty array since event went to DLQ
            expect(results).toHaveLength(0)
            expect(mockKafkaProducer.produce).toHaveBeenCalledWith(
                expect.objectContaining({
                    topic: 'test-dlq-topic',
                    value: messages[0].value,
                    key: messages[0].key,
                })
            )

            // Verify mock step was called with correct arguments
            expect(step1).toHaveBeenCalledTimes(1)
            expect(step1).toHaveBeenCalledWith({ message: messages[0] })
        })

        it('should process events concurrently while preserving final ordering', async () => {
            const messages: Message[] = [
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    value: Buffer.from('event-1'),
                    timestamp: Date.now(),
                } as Message,
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 2,
                    key: Buffer.from('key2'),
                    value: Buffer.from('event-2'),
                    timestamp: Date.now() + 1,
                } as Message,
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 3,
                    key: Buffer.from('key3'),
                    value: Buffer.from('event-3'),
                    timestamp: Date.now() + 2,
                } as Message,
            ]

            // Define result maps
            const step1Map = new Map<string, PipelineResult<{ message: Message; headers: TestHeaders }>>([
                ['event-1', ok({ message: messages[0], headers: { token: 'test-token' } })],
                ['event-2', ok({ message: messages[1], headers: { token: 'test-token' } })],
                ['event-3', ok({ message: messages[2], headers: { token: 'test-token' } })],
            ])
            const step2Map = new Map<
                string,
                PipelineResult<{ message: Message; headers: TestHeaders; event: TestEvent }>
            >([
                [
                    'event-1',
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-1', event: 'test-event', token: 'test-token' },
                    }),
                ],
                [
                    'event-2',
                    ok({
                        message: messages[1],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-2', event: 'test-event', token: 'test-token' },
                    }),
                ],
                [
                    'event-3',
                    ok({
                        message: messages[2],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-3', event: 'test-event', token: 'test-token' },
                    }),
                ],
            ])
            const asyncStep3Map = new Map<string, AsyncStepConfig<TestEventWithTeam>>([
                [
                    'event-1',
                    {
                        delay: 5,
                        result: ok({
                            message: messages[0],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event-1', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
                [
                    'event-2',
                    {
                        delay: 15,
                        result: ok({
                            message: messages[1],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event-2', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
                [
                    'event-3',
                    {
                        delay: 10,
                        result: ok({
                            message: messages[2],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event-3', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
            ])

            // Define batch step result map
            const batchStep4Map = new Map<number, PipelineResult<TestEventWithTeam>>([
                [
                    0,
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-1', event: 'test-event', token: 'test-token', batch_result: 'processed' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    1,
                    ok({
                        message: messages[1],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-2', event: 'test-event', token: 'test-token', batch_result: 'processed' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    2,
                    ok({
                        message: messages[2],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-3', event: 'test-event', token: 'test-token', batch_result: 'processed' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
            ])

            // Define steps
            const step1 = createMockStep<{ message: Message }, { message: Message; headers: TestHeaders }>(step1Map)
            const step2 = createMockStep<
                { message: Message; headers: TestHeaders },
                { message: Message; headers: TestHeaders; event: TestEvent }
            >(step2Map)
            const asyncStep3 = createMockAsyncStep<
                { message: Message; headers: TestHeaders; event: TestEvent },
                TestEventWithTeam
            >(asyncStep3Map)

            // Define batch step
            const batchStep4 = createMockBatchStep<TestEventWithTeam, TestEventWithTeam>(batchStep4Map)

            // Create pipeline
            const preprocessingPipeline = createNewPipeline().pipe(step1).pipe(step2).pipeAsync(asyncStep3)

            const batchPipeline = createNewBatchPipeline()
                .pipeConcurrently(preprocessingPipeline)
                .gather()
                .pipeBatch(batchStep4)

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, pipelineConfig)

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            const results = await resultHandlingPipeline.next()

            expect(results).toHaveLength(3)
            // Verify final ordering is preserved despite concurrent preprocessing
            expect((results![0] as TestEventWithTeam).event.uuid).toBe('event-1')
            expect((results![1] as TestEventWithTeam).event.uuid).toBe('event-2')
            expect((results![2] as TestEventWithTeam).event.uuid).toBe('event-3')

            // Verify batch step added processing metadata to all events
            expect((results![0] as TestEventWithTeam).event.batch_result).toBe('processed')
            expect((results![1] as TestEventWithTeam).event.batch_result).toBe('processed')
            expect((results![2] as TestEventWithTeam).event.batch_result).toBe('processed')

            // Verify mock steps were called with correct arguments
            expect(step1).toHaveBeenCalledTimes(3)
            expect(step2).toHaveBeenCalledTimes(3)
            expect(asyncStep3).toHaveBeenCalledTimes(3)

            // Verify batch step was called with events in correct order
            expect(batchStep4).toHaveBeenCalledTimes(1)
            expect(batchStep4).toHaveBeenNthCalledWith(
                1,
                expect.arrayContaining([
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event-1' }) }),
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event-2' }) }),
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event-3' }) }),
                ])
            )
        })

        it('should handle mixed success and failure scenarios in batch', async () => {
            const messages: Message[] = [
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    value: Buffer.from('event1'),
                    timestamp: Date.now(),
                } as Message,
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 2,
                    key: Buffer.from('key2'),
                    value: Buffer.from('drop-event'),
                    timestamp: Date.now() + 1,
                } as Message,
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 3,
                    key: Buffer.from('key3'),
                    value: Buffer.from('event3'),
                    timestamp: Date.now() + 2,
                } as Message,
            ]

            // Define result maps
            const step1Map = new Map<string, PipelineResult<{ message: Message; headers: TestHeaders }>>([
                ['event1', ok({ message: messages[0], headers: { token: 'test-token' } })],
                ['drop-event', drop('Mock drop')],
                ['event3', ok({ message: messages[2], headers: { token: 'test-token' } })],
            ])
            const step2Map = new Map<
                string,
                PipelineResult<{ message: Message; headers: TestHeaders; event: TestEvent }>
            >([
                [
                    'event1',
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event1', event: 'test-event', token: 'test-token' },
                    }),
                ],
                [
                    'event3',
                    ok({
                        message: messages[2],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event3', event: 'test-event', token: 'test-token' },
                    }),
                ],
            ])
            const asyncStep3Map = new Map<string, AsyncStepConfig<TestEventWithTeam>>([
                [
                    'event1',
                    {
                        delay: 8,
                        result: ok({
                            message: messages[0],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event1', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
                [
                    'event3',
                    {
                        delay: 6,
                        result: ok({
                            message: messages[2],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event3', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
            ])

            // Define batch step result map
            const batchStep4Map = new Map<number, PipelineResult<TestEventWithTeam>>([
                [
                    0,
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event1', event: 'test-event', token: 'test-token', batch_result: 'processed' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    1,
                    ok({
                        message: messages[2],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event3', event: 'test-event', token: 'test-token', batch_result: 'processed' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
            ])

            // Define steps
            const step1 = createMockStep<{ message: Message }, { message: Message; headers: TestHeaders }>(step1Map)
            const step2 = createMockStep<
                { message: Message; headers: TestHeaders },
                { message: Message; headers: TestHeaders; event: TestEvent }
            >(step2Map)
            const asyncStep3 = createMockAsyncStep<
                { message: Message; headers: TestHeaders; event: TestEvent },
                TestEventWithTeam
            >(asyncStep3Map)

            // Define batch step
            const batchStep4 = createMockBatchStep<TestEventWithTeam, TestEventWithTeam>(batchStep4Map)

            // Create pipeline
            const preprocessingPipeline = createNewPipeline().pipe(step1).pipe(step2).pipeAsync(asyncStep3)

            const batchPipeline = createNewBatchPipeline()
                .pipeConcurrently(preprocessingPipeline)
                .gather()
                .pipeBatch(batchStep4)

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, pipelineConfig)

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            const results = await resultHandlingPipeline.next()

            // Should only return the valid events
            expect(results).toHaveLength(2)
            expect((results![0] as TestEventWithTeam).event.uuid).toBe('event1')
            expect((results![1] as TestEventWithTeam).event.uuid).toBe('event3')

            // Verify batch step added processing metadata
            expect((results![0] as TestEventWithTeam).event.batch_result).toBe('processed')
            expect((results![1] as TestEventWithTeam).event.batch_result).toBe('processed')

            // Verify mock steps were called with correct arguments
            expect(step1).toHaveBeenCalledTimes(3)
            expect(step2).toHaveBeenCalledTimes(2) // Only valid events reach validation
            expect(asyncStep3).toHaveBeenCalledTimes(2) // Only valid events reach team resolution
            expect(batchStep4).toHaveBeenCalledTimes(1) // Batch step called once with 2 events

            // Verify batch step was called with remaining events in correct order (dropped event excluded)
            expect(batchStep4).toHaveBeenNthCalledWith(
                1,
                expect.arrayContaining([
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event1' }) }),
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event3' }) }),
                ])
            )
        })
    })

    describe('Error Handling', () => {
        it('should handle exceptions in preprocessing steps', async () => {
            const messages: Message[] = [
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    value: Buffer.from('event1'),
                    timestamp: 1234567890,
                    size: 6,
                },
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 2,
                    key: Buffer.from('key2'),
                    value: Buffer.from('event2'),
                    timestamp: 1234567891,
                    size: 6,
                },
            ]

            // Define result maps
            const step1Map = new Map<string, PipelineResult<{ message: Message; headers: TestHeaders }>>([
                ['event1', ok({ message: messages[0], headers: { token: 'test-token' } })],
                ['event2', ok({ message: messages[1], headers: { token: 'test-token' } })],
            ])

            // Define batch step result map
            const batchStep4Map = new Map<number, PipelineResult<TestEventWithTeam>>([
                [
                    0,
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: {
                            uuid: 'event1',
                            event: 'test-event-0',
                            token: 'test-token',
                            batch_result: 'processed',
                        },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    1,
                    ok({
                        message: messages[1],
                        headers: { token: 'test-token' },
                        event: {
                            uuid: 'event2',
                            event: 'test-event-1',
                            token: 'test-token',
                            batch_result: 'processed',
                        },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
            ])

            // Define steps
            const step1 = createMockStep<{ message: Message }, { message: Message; headers: TestHeaders }>(step1Map)

            // Create a step that throws an exception for one event
            const step2 = jest.fn(
                async (input: {
                    message: Message
                    headers: TestHeaders
                }): Promise<PipelineResult<{ message: Message; headers: TestHeaders; event: TestEvent }>> => {
                    await new Promise((resolve) => setTimeout(resolve, 1)) // Simulate async work
                    const eventId = input.message.value?.toString() || 'unknown'
                    if (eventId === 'event1') {
                        throw new Error('Mock preprocessing exception')
                    }
                    return ok({
                        message: input.message,
                        headers: input.headers,
                        event: { uuid: eventId, event: 'test-event', token: 'test-token' },
                    })
                }
            )

            const step3Map = new Map<string, AsyncStepConfig<TestEventWithTeam>>([
                [
                    'event2',
                    {
                        delay: 10,
                        result: ok({
                            message: messages[1],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event2', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
            ])
            const step3 = createMockAsyncStep<
                { message: Message; headers: TestHeaders; event: TestEvent },
                TestEventWithTeam
            >(step3Map)

            const batchStep4 = createMockBatchStep<TestEventWithTeam, TestEventWithTeam>(batchStep4Map)

            // Create pipeline
            const preprocessingPipeline = createNewPipeline().pipe(step1).pipeAsync(step2).pipeAsync(step3)

            const batchPipeline = createNewBatchPipeline()
                .pipeConcurrently(preprocessingPipeline)
                .gather()
                .pipeBatch(batchStep4)

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, {
                kafkaProducer: mockKafkaProducer,
                dlqTopic: 'dlq-topic',
                promiseScheduler: mockPromiseScheduler,
            })

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            // Expect the pipeline to throw an exception
            await expect(resultHandlingPipeline.next()).rejects.toThrow('Mock preprocessing exception')

            // Verify preprocessing steps were called
            expect(step1).toHaveBeenCalledTimes(2)
            expect(step2).toHaveBeenCalledTimes(2)
            // Note: step3 call count is not deterministic due to concurrent processing and exception handling

            // Verify batch step was not called due to exception
            expect(batchStep4).toHaveBeenCalledTimes(0)
        })

        it('should handle exceptions in batch steps', async () => {
            const messages: Message[] = [
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    value: Buffer.from('event1'),
                    timestamp: 1234567890,
                    size: 6,
                },
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 2,
                    key: Buffer.from('key2'),
                    value: Buffer.from('event2'),
                    timestamp: 1234567891,
                    size: 6,
                },
            ]

            // Define result maps
            const step1Map = new Map<string, PipelineResult<TestEventWithTeam>>([
                [
                    'event1',
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event1', event: 'test-event', token: 'test-token' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    'event2',
                    ok({
                        message: messages[1],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event2', event: 'test-event', token: 'test-token' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
            ])

            // Define batch step result maps
            const batchStep1Map = new Map<number, PipelineResult<TestEventWithTeam>>([
                [
                    0,
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: {
                            uuid: 'event1',
                            event: 'test-event-0',
                            token: 'test-token',
                            batch_result: 'processed',
                        },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    1,
                    ok({
                        message: messages[1],
                        headers: { token: 'test-token' },
                        event: {
                            uuid: 'event2',
                            event: 'test-event-1',
                            token: 'test-token',
                            batch_result: 'processed',
                        },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
            ])

            const batchStep3Map = new Map<number, PipelineResult<TestEventWithTeam>>([
                [
                    0,
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: {
                            uuid: 'event1',
                            event: 'test-event-0',
                            token: 'test-token',
                            batch_result: 'processed',
                        },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    1,
                    ok({
                        message: messages[1],
                        headers: { token: 'test-token' },
                        event: {
                            uuid: 'event2',
                            event: 'test-event-1',
                            token: 'test-token',
                            batch_result: 'processed',
                        },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
            ])

            // Define steps
            const step1 = createMockStep<{ message: Message }, TestEventWithTeam>(step1Map)

            const batchStep1 = createMockBatchStep<TestEventWithTeam, TestEventWithTeam>(batchStep1Map)

            // Create a batch step that throws an exception
            const batchStep2 = jest.fn(
                async (_events: TestEventWithTeam[]): Promise<PipelineResult<TestEventWithTeam>[]> => {
                    await new Promise((resolve) => setTimeout(resolve, 1)) // Simulate async work
                    throw new Error('Mock batch exception')
                }
            )

            const batchStep3 = createMockBatchStep<TestEventWithTeam, TestEventWithTeam>(batchStep3Map)

            // Create pipeline
            const preprocessingPipeline = createNewPipeline().pipe(step1)

            const gatheredPipeline = createNewBatchPipeline().pipeConcurrently(preprocessingPipeline).gather()

            const batchPipeline1 = gatheredPipeline.pipeBatch(batchStep1)
            const batchPipeline2 = new SequentialBatchPipeline(batchStep2, batchPipeline1)
            const batchPipeline = new SequentialBatchPipeline(batchStep3, batchPipeline2)

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, {
                kafkaProducer: mockKafkaProducer,
                dlqTopic: 'dlq-topic',
                promiseScheduler: mockPromiseScheduler,
            })

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            // Expect the pipeline to throw an exception
            await expect(resultHandlingPipeline.next()).rejects.toThrow('Mock batch exception')

            // Verify preprocessing step was called
            expect(step1).toHaveBeenCalledTimes(2)

            // Verify batch steps were called up to the exception
            expect(batchStep1).toHaveBeenCalledTimes(1)
            expect(batchStep2).toHaveBeenCalledTimes(1)

            // Verify third batch step was not called due to exception
            expect(batchStep3).toHaveBeenCalledTimes(0)
        })

        it('should handle mixed results and exceptions without producing to Kafka', async () => {
            const messages: Message[] = [
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    value: Buffer.from('drop-event'),
                    timestamp: 1234567890,
                    size: 10,
                },
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 2,
                    key: Buffer.from('key2'),
                    value: Buffer.from('dlq-event'),
                    timestamp: 1234567891,
                    size: 8,
                },
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 3,
                    key: Buffer.from('key3'),
                    value: Buffer.from('redirect-event'),
                    timestamp: 1234567892,
                    size: 13,
                },
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 4,
                    key: Buffer.from('key4'),
                    value: Buffer.from('ok-event'),
                    timestamp: 1234567893,
                    size: 7,
                },
            ]

            // Define result maps
            const step1Map = new Map<string, PipelineResult<{ message: Message; headers: TestHeaders }>>([
                ['drop-event', drop('Mock drop')],
                ['dlq-event', dlq('Mock DLQ')],
                ['redirect-event', redirect('Mock redirect', 'redirect-topic', true)],
                ['ok-event', ok({ message: messages[3], headers: { token: 'test-token' } })],
            ])

            // Define steps
            const step1 = createMockStep<{ message: Message }, { message: Message; headers: TestHeaders }>(step1Map)

            // Create a step that throws an exception for the remaining event
            const step2 = jest.fn(
                async (_input: {
                    message: Message
                    headers: TestHeaders
                }): Promise<PipelineResult<{ message: Message; headers: TestHeaders; event: TestEvent }>> => {
                    await new Promise((resolve) => setTimeout(resolve, 1)) // Simulate async work
                    throw new Error('Mock step2 exception')
                }
            )

            // Create pipeline
            const preprocessingPipeline = createNewPipeline().pipe(step1).pipeAsync(step2)

            const batchPipeline = createNewBatchPipeline().pipeConcurrently(preprocessingPipeline).gather()

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, {
                kafkaProducer: mockKafkaProducer,
                dlqTopic: 'dlq-topic',
                promiseScheduler: mockPromiseScheduler,
            })

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            // Expect the pipeline to throw an exception
            await expect(resultHandlingPipeline.next()).rejects.toThrow('Mock step2 exception')

            // Verify preprocessing steps were called
            expect(step1).toHaveBeenCalledTimes(4)
            expect(step2).toHaveBeenCalledTimes(1) // Only ok-event reaches step2

            // Verify no messages were produced to Kafka due to exception
            expect(mockKafkaProducer.produce).toHaveBeenCalledTimes(0)
        })
    })

    describe('Concurrent Processing', () => {
        it('should preserve ordering with pipeConcurrently and gather using deterministic mocks', async () => {
            const messages: Message[] = [
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    value: Buffer.from('event1'),
                    timestamp: 1234567890,
                    size: 6,
                },
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 2,
                    key: Buffer.from('key2'),
                    value: Buffer.from('event2'),
                    timestamp: 1234567891,
                    size: 6,
                },
                {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 3,
                    key: Buffer.from('key3'),
                    value: Buffer.from('event3'),
                    timestamp: 1234567892,
                    size: 6,
                },
            ]

            // Create promises with stored resolve callbacks for manual control
            let resolve1: () => void
            let resolve2: () => void
            let resolve3: () => void

            const promise1 = new Promise<void>((resolve) => {
                resolve1 = resolve
            })
            const promise2 = new Promise<void>((resolve) => {
                resolve2 = resolve
            })
            const promise3 = new Promise<void>((resolve) => {
                resolve3 = resolve
            })

            // Define result maps
            const step1Map = new Map<string, PipelineResult<{ message: Message; headers: TestHeaders }>>([
                ['event1', ok({ message: messages[0], headers: { token: 'test-token' } })],
                ['event2', ok({ message: messages[1], headers: { token: 'test-token' } })],
                ['event3', ok({ message: messages[2], headers: { token: 'test-token' } })],
            ])

            // Create deterministic async step that waits for manual resolution
            let callCount = 0
            const asyncStep2 = jest.fn(
                async (input: {
                    message: Message
                    headers: TestHeaders
                }): Promise<PipelineResult<TestEventWithTeam>> => {
                    const eventId = input.message.value?.toString() || 'unknown'
                    const currentCall = callCount++

                    // Wait for the appropriate promise to be manually resolved
                    if (currentCall === 0) {
                        await promise1
                    } else if (currentCall === 1) {
                        await promise2
                    } else if (currentCall === 2) {
                        await promise3
                    }

                    return ok({
                        message: input.message,
                        headers: input.headers,
                        event: { uuid: eventId, event: 'test-event', token: 'test-token' },
                        team: { id: 1, name: 'Test Team' },
                    })
                }
            )

            // Define steps
            const step1 = createMockStep<{ message: Message }, { message: Message; headers: TestHeaders }>(step1Map)

            // Create pipeline
            const preprocessingPipeline = createNewPipeline().pipe(step1).pipeAsync(asyncStep2)

            const batchPipeline = createNewBatchPipeline().pipeConcurrently(preprocessingPipeline).gather()

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, {
                kafkaProducer: mockKafkaProducer,
                dlqTopic: 'dlq-topic',
                promiseScheduler: mockPromiseScheduler,
            })

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            // Start the pipeline processing
            const resultsPromise = resultHandlingPipeline.next()

            // Resolve promises in specific order to test ordering preservation
            // 1. Resolve second promise first
            resolve2!()
            await new Promise((resolve) => setImmediate(resolve)) // Wait for next tick

            // Check that results promise is not resolved yet (waiting for other promises)
            const isResolvedAfter2 = await Promise.race([
                resultsPromise.then(() => true),
                new Promise((resolve) => setImmediate(() => resolve(false))),
            ])
            expect(isResolvedAfter2).toBe(false)

            // 2. Resolve first promise
            resolve1!()
            await new Promise((resolve) => setImmediate(resolve)) // Wait for next tick

            // Check that results promise is still not resolved (waiting for third promise)
            const isResolvedAfter1 = await Promise.race([
                resultsPromise.then(() => true),
                new Promise((resolve) => setImmediate(() => resolve(false))),
            ])
            expect(isResolvedAfter1).toBe(false)

            // 3. Resolve third promise last
            resolve3!()
            await new Promise((resolve) => setImmediate(resolve)) // Wait for next tick

            const results = await resultsPromise

            expect(results).toHaveLength(3)

            // Verify ordering is preserved despite concurrent processing and manual resolution order
            expect((results![0] as TestEventWithTeam).event.uuid).toBe('event1')
            expect((results![1] as TestEventWithTeam).event.uuid).toBe('event2')
            expect((results![2] as TestEventWithTeam).event.uuid).toBe('event3')

            // Verify mock steps were called with correct arguments
            expect(step1).toHaveBeenCalledTimes(3)
            expect(asyncStep2).toHaveBeenCalledTimes(3)
        })

        it('should process multiple events concurrently while maintaining ordering', async () => {
            const messages: Message[] = Array.from(
                { length: 5 },
                (_, i) =>
                    ({
                        topic: 'test-topic',
                        partition: 0,
                        offset: i + 1,
                        key: Buffer.from(`key${i}`),
                        value: Buffer.from(`event-${i}`),
                        timestamp: Date.now() + i,
                    }) as Message
            )

            // Define result maps
            const step1Map = new Map<string, PipelineResult<{ message: Message; headers: TestHeaders }>>([
                ['event-0', ok({ message: messages[0], headers: { token: 'test-token' } })],
                ['event-1', ok({ message: messages[1], headers: { token: 'test-token' } })],
                ['event-2', ok({ message: messages[2], headers: { token: 'test-token' } })],
                ['event-3', ok({ message: messages[3], headers: { token: 'test-token' } })],
                ['event-4', ok({ message: messages[4], headers: { token: 'test-token' } })],
            ])
            const step2Map = new Map<
                string,
                PipelineResult<{ message: Message; headers: TestHeaders; event: TestEvent }>
            >([
                [
                    'event-0',
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-0', event: 'test-event', token: 'test-token' },
                    }),
                ],
                [
                    'event-1',
                    ok({
                        message: messages[1],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-1', event: 'test-event', token: 'test-token' },
                    }),
                ],
                [
                    'event-2',
                    ok({
                        message: messages[2],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-2', event: 'test-event', token: 'test-token' },
                    }),
                ],
                [
                    'event-3',
                    ok({
                        message: messages[3],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-3', event: 'test-event', token: 'test-token' },
                    }),
                ],
                [
                    'event-4',
                    ok({
                        message: messages[4],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-4', event: 'test-event', token: 'test-token' },
                    }),
                ],
            ])
            const asyncStep3Map = new Map<string, AsyncStepConfig<TestEventWithTeam>>([
                [
                    'event-0',
                    {
                        delay: 20,
                        result: ok({
                            message: messages[0],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event-0', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
                [
                    'event-1',
                    {
                        delay: 15,
                        result: ok({
                            message: messages[1],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event-1', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
                [
                    'event-2',
                    {
                        delay: 25,
                        result: ok({
                            message: messages[2],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event-2', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
                [
                    'event-3',
                    {
                        delay: 10,
                        result: ok({
                            message: messages[3],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event-3', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
                [
                    'event-4',
                    {
                        delay: 30,
                        result: ok({
                            message: messages[4],
                            headers: { token: 'test-token' },
                            event: { uuid: 'event-4', event: 'test-event', token: 'test-token' },
                            team: { id: 1, name: 'Test Team' },
                        }),
                    },
                ],
            ])

            // Define batch step result map
            const batchStep4Map = new Map<number, PipelineResult<TestEventWithTeam>>([
                [
                    0,
                    ok({
                        message: messages[0],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-0', event: 'test-event', token: 'test-token', batch_result: 'processed' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    1,
                    ok({
                        message: messages[1],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-1', event: 'test-event', token: 'test-token', batch_result: 'processed' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    2,
                    ok({
                        message: messages[2],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-2', event: 'test-event', token: 'test-token', batch_result: 'processed' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    3,
                    ok({
                        message: messages[3],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-3', event: 'test-event', token: 'test-token', batch_result: 'processed' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
                [
                    4,
                    ok({
                        message: messages[4],
                        headers: { token: 'test-token' },
                        event: { uuid: 'event-4', event: 'test-event', token: 'test-token', batch_result: 'processed' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                ],
            ])

            // Define steps
            const step1 = createMockStep<{ message: Message }, { message: Message; headers: TestHeaders }>(step1Map)
            const step2 = createMockStep<
                { message: Message; headers: TestHeaders },
                { message: Message; headers: TestHeaders; event: TestEvent }
            >(step2Map)
            const asyncStep3 = createMockAsyncStep<
                { message: Message; headers: TestHeaders; event: TestEvent },
                TestEventWithTeam
            >(asyncStep3Map)

            // Define batch step
            const batchStep4 = createMockBatchStep<TestEventWithTeam, TestEventWithTeam>(batchStep4Map)

            // Create pipeline
            const preprocessingPipeline = createNewPipeline().pipe(step1).pipe(step2).pipeAsync(asyncStep3)

            const batchPipeline = createNewBatchPipeline()
                .pipeConcurrently(preprocessingPipeline)
                .gather()
                .pipeBatch(batchStep4)

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, pipelineConfig)

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            const results = await resultHandlingPipeline.next()

            expect(results).toHaveLength(5)
            // Verify final ordering is preserved despite concurrent preprocessing
            for (let i = 0; i < 5; i++) {
                expect((results![i] as TestEventWithTeam).event.uuid).toBe(`event-${i}`)
            }

            // Verify mock steps were called with correct arguments
            expect(step1).toHaveBeenCalledTimes(5)
            expect(step2).toHaveBeenCalledTimes(5)
            expect(asyncStep3).toHaveBeenCalledTimes(5)

            // Verify batch step was called with events in correct order
            expect(batchStep4).toHaveBeenCalledTimes(1)
            expect(batchStep4).toHaveBeenNthCalledWith(
                1,
                expect.arrayContaining([
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event-0' }) }),
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event-1' }) }),
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event-2' }) }),
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event-3' }) }),
                    expect.objectContaining({ event: expect.objectContaining({ uuid: 'event-4' }) }),
                ])
            )
        })
    })

    describe('Performance and Concurrency', () => {
        it('should process 100 events with random delays efficiently', async () => {
            const messages: Message[] = Array.from(
                { length: 100 },
                (_, i) =>
                    ({
                        topic: 'test-topic',
                        partition: 0,
                        offset: i + 1,
                        key: Buffer.from(`key${i}`),
                        value: Buffer.from(`event-${i}`),
                        timestamp: Date.now() + i,
                    }) as Message
            )

            // Create result map with random delays between 50-150ms
            const asyncStep1Map = new Map<string, AsyncStepConfig<TestEventWithTeam>>()
            for (let i = 0; i < 100; i++) {
                const randomDelay = Math.floor(Math.random() * 100) + 50 // 50-150ms
                asyncStep1Map.set(`event-${i}`, {
                    delay: randomDelay,
                    result: ok({
                        message: messages[i],
                        headers: { token: 'test-token' },
                        event: { uuid: `event-${i}`, event: 'test-event', token: 'test-token' },
                        team: { id: 1, name: 'Test Team' },
                    }),
                })
            }

            // Define batch step result map
            const batchStep2Map = new Map<number, PipelineResult<TestEventWithTeam>>()
            for (let i = 0; i < 100; i++) {
                batchStep2Map.set(
                    i,
                    ok({
                        message: messages[i],
                        headers: { token: 'test-token' },
                        event: {
                            uuid: `event-${i}`,
                            event: 'test-event',
                            token: 'test-token',
                            batch_result: 'processed',
                        },
                        team: { id: 1, name: 'Test Team' },
                    })
                )
            }

            // Define step with random delays
            const asyncStep1 = createMockAsyncStep<{ message: Message }, TestEventWithTeam>(asyncStep1Map)

            // Define batch step
            const batchStep2 = createMockBatchStep<TestEventWithTeam, TestEventWithTeam>(batchStep2Map)

            // Create pipeline with single async step
            const preprocessingPipeline = createNewPipeline().pipeAsync(asyncStep1)

            const batchPipeline = createNewBatchPipeline()
                .pipeConcurrently(preprocessingPipeline)
                .gather()
                .pipeBatch(batchStep2)

            const resultHandlingPipeline = ResultHandlingPipeline.of(batchPipeline, pipelineConfig)

            const batch = createBatch(messages)
            resultHandlingPipeline.feed(batch)

            const startTime = Date.now()
            const results = await resultHandlingPipeline.next()
            const endTime = Date.now()

            // Verify all events were processed
            expect(results).toHaveLength(100)

            // Verify ordering is preserved
            for (let i = 0; i < 100; i++) {
                expect((results![i] as TestEventWithTeam).event.uuid).toBe(`event-${i}`)
            }

            // Assert pipeline completes within reasonable time (50-300ms with safety margin)
            const totalTime = endTime - startTime
            expect(totalTime).toBeGreaterThanOrEqual(50) // At least 50ms due to minimum delay
            expect(totalTime).toBeLessThanOrEqual(300) // Should complete within 300ms due to concurrency

            // Verify mock step was called for all events
            expect(asyncStep1).toHaveBeenCalledTimes(100)
        })
    })
})
