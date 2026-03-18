/**
 * # Chapter 7: Result Handling (DLQ, DROP, REDIRECT)
 *
 * After processing items through pipeline steps, results need to be handled
 * properly. OK results continue through the pipeline, but non-OK results
 * (DLQ, DROP, REDIRECT) require special handling.
 *
 * The `handleResults()` method processes non-OK results by converting them
 * into appropriate side effects:
 *
 * - **DLQ**: Send to dead-letter topic with error details
 * - **DROP**: Log and discard (no Kafka message)
 * - **REDIRECT**: Send to an alternate topic
 *
 * ## Accessing handleResults()
 *
 * `handleResults()` is available through the `messageAware()` builder method.
 * This requires the pipeline context to include the Kafka message, as result
 * handling needs access to the original message for DLQ entries.
 *
 * ```typescript
 * newBatchPipelineBuilder<T, { message: Message }>()
 *   .messageAware((builder) =>
 *     builder
 *       .concurrently(...)
 *       .handleResults(config)
 *   )
 * ```
 *
 * Only Kafka message context is supported.
 *
 * ## Configuration
 *
 * `handleResults()` requires a `PipelineConfig` with:
 * - `kafkaProducer`: For sending messages to DLQ and redirect topics
 * - `dlqTopic`: The dead-letter topic name
 * - `promiseScheduler`: For scheduling async operations
 *
 * ## Required: handleSideEffects()
 *
 * After calling `handleResults()`, you **must** call `handleSideEffects()`
 * before calling `build()`. This is enforced by the builder types - the
 * `build()` method is not available until `handleSideEffects()` is called.
 *
 * ```typescript
 * newBatchPipelineBuilder<T, { message: Message }>()
 *   .pipeBatch(processStep())
 *   .messageAware((builder) => builder)
 *   .handleResults(config)
 *   .handleSideEffects(promiseScheduler, { await: true })  // Required!
 *   .build()
 * ```
 */
import { Message } from 'node-rdkafka'

import { createTestMessage } from '../../../../tests/helpers/kafka-message'
import { PromiseScheduler } from '../../../utils/promise-scheduler'
import { newBatchPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { PipelineResult, dlq, drop, isDlqResult, isDropResult, isRedirectResult, ok, redirect } from '../results'

type BatchProcessingStep<T, U> = (values: T[]) => Promise<PipelineResult<U>[]>

describe('Result Handling', () => {
    /**
     * DLQ (Dead Letter Queue) results send failed items to a dedicated topic
     * for later analysis or reprocessing. The DLQ message includes:
     * - The original Kafka message
     * - The error reason
     * - The error object (if provided)
     * - The step name where the failure occurred
     */
    it('DLQ sends failed items to dead-letter topic with error details', async () => {
        const producedMessages: any[] = []

        const mockProducer = {
            produce: jest.fn((msg) => {
                producedMessages.push(msg)
                return Promise.resolve()
            }),
        }

        const promiseScheduler = new PromiseScheduler()

        const pipelineConfig = {
            kafkaProducer: mockProducer as any,
            dlqTopic: 'my-dlq-topic',
            promiseScheduler: promiseScheduler,
        }

        interface Event {
            data: string
        }

        function createValidationStep(): BatchProcessingStep<Event, Event> {
            return function validationStep(items) {
                return Promise.resolve(
                    items.map((item) =>
                        item.data === 'invalid' ? dlq('Validation failed', new Error('Invalid data format')) : ok(item)
                    )
                )
            }
        }

        const pipeline = newBatchPipelineBuilder<Event, { message: Message }>()
            .pipeBatch(createValidationStep())
            .messageAware((builder) => builder)
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const message = createTestMessage()
        const batch = [createContext(ok({ data: 'invalid' }), { message })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        // Result is marked as DLQ
        expect(results).toHaveLength(1)
        expect(isDlqResult(results![0].result)).toBe(true)

        // Message was sent to DLQ topic with all expected fields
        expect(mockProducer.produce).toHaveBeenCalledTimes(1)
        const dlqMessage = producedMessages[0]
        expect(dlqMessage.topic).toBe('my-dlq-topic')
        expect(dlqMessage.value).toEqual(message.value)
        expect(dlqMessage.key).toEqual(message.key)
        expect(dlqMessage.headers).toMatchObject({
            dlq_reason: 'Invalid data format',
            dlq_step: 'validationStep',
        })
        expect(dlqMessage.headers['dlq_timestamp']).toBeDefined()
    })

    /**
     * DROP results silently discard items without sending them anywhere.
     * This is useful for filtering out items that don't need processing
     * (e.g., internal events, duplicates, or items outside scope).
     */
    it('DROP discards items without sending to Kafka', async () => {
        const mockProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
        }

        const promiseScheduler = new PromiseScheduler()

        const pipelineConfig = {
            kafkaProducer: mockProducer as any,
            dlqTopic: 'dlq-topic',
            promiseScheduler: promiseScheduler,
        }

        interface Event {
            eventType: string
        }

        function createFilterStep(): BatchProcessingStep<Event, Event> {
            return function filterStep(items) {
                return Promise.resolve(
                    items.map((item) =>
                        item.eventType.startsWith('internal-') ? drop('Internal event filtered') : ok(item)
                    )
                )
            }
        }

        const pipeline = newBatchPipelineBuilder<Event, { message: Message }>()
            .pipeBatch(createFilterStep())
            .messageAware((builder) => builder)
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const message = createTestMessage()
        const batch = [createContext(ok({ eventType: 'internal-heartbeat' }), { message })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        // Result is marked as DROP
        expect(results).toHaveLength(1)
        expect(isDropResult(results![0].result)).toBe(true)

        // No Kafka produce for dropped messages
        expect(mockProducer.produce).not.toHaveBeenCalled()
    })

    /**
     * REDIRECT results send items to a different topic for alternative
     * processing. This is useful for routing items based on content
     * (e.g., high-priority events to a fast-track topic). The original
     * message key can optionally be preserved or discarded.
     */
    it('REDIRECT sends items to specified topic with optional key preservation', async () => {
        const producedMessages: any[] = []

        const mockProducer = {
            produce: jest.fn((msg) => {
                producedMessages.push(msg)
                return Promise.resolve()
            }),
        }

        const promiseScheduler = new PromiseScheduler()

        const pipelineConfig = {
            kafkaProducer: mockProducer as any,
            dlqTopic: 'dlq-topic',
            promiseScheduler: promiseScheduler,
        }

        interface Event {
            priority: string
        }

        function createRoutingStep(): BatchProcessingStep<Event, Event> {
            return function routingStep(items) {
                return Promise.resolve(
                    items.map((item) => {
                        if (item.priority === 'high') {
                            return redirect('High priority routing', 'high-priority-topic', true) // preserveKey = true
                        } else if (item.priority === 'broadcast') {
                            return redirect('Broadcast routing', 'broadcast-topic', false) // preserveKey = false
                        }
                        return ok(item)
                    })
                )
            }
        }

        const pipeline = newBatchPipelineBuilder<Event, { message: Message }>()
            .pipeBatch(createRoutingStep())
            .messageAware((builder) => builder)
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const originalKey = Buffer.from('my-partition-key')
        const message1 = createTestMessage({ key: originalKey })
        const message2 = createTestMessage({ key: Buffer.from('another-key') })
        const batch = [
            createContext(ok({ priority: 'high' }), { message: message1 }),
            createContext(ok({ priority: 'broadcast' }), { message: message2 }),
        ]
        pipeline.feed(batch)

        const results = await pipeline.next()

        // Both results are marked as REDIRECT
        expect(results).toHaveLength(2)
        expect(isRedirectResult(results![0].result)).toBe(true)
        expect(isRedirectResult(results![1].result)).toBe(true)

        // Two messages were produced
        expect(mockProducer.produce).toHaveBeenCalledTimes(2)

        // First message: key preserved
        const preservedKeyMessage = producedMessages[0]
        expect(preservedKeyMessage.topic).toBe('high-priority-topic')
        expect(preservedKeyMessage.value).toEqual(message1.value)
        expect(preservedKeyMessage.key).toEqual(originalKey)
        expect(preservedKeyMessage.headers).toMatchObject({
            'redirect-step': 'routingStep',
        })
        expect(preservedKeyMessage.headers['redirect-timestamp']).toBeDefined()

        // Second message: key discarded
        const discardedKeyMessage = producedMessages[1]
        expect(discardedKeyMessage.topic).toBe('broadcast-topic')
        expect(discardedKeyMessage.value).toEqual(message2.value)
        expect(discardedKeyMessage.key).toBeNull()
        expect(discardedKeyMessage.headers).toMatchObject({
            'redirect-step': 'routingStep',
        })
        expect(discardedKeyMessage.headers['redirect-timestamp']).toBeDefined()
    })
})
