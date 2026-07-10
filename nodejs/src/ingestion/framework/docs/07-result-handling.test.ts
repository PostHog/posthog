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
 * - **REDIRECT**: Send to a named output (e.g. overflow)
 *
 * ## Redirect Options
 *
 * `redirect(reason, output, preserveKey?, awaitAck?)` takes two optional flags,
 * both defaulting to `true`:
 *
 * - **`preserveKey`** (default `true`): keep the original Kafka message key on
 *   the redirected message so partitioning/ordering is retained. Pass `false`
 *   to drop the key (the message is produced with a `null` key, letting the
 *   broker assign a partition).
 * - **`awaitAck`** (default `true`): wait for the broker to acknowledge the
 *   redirected produce before the result is finalized. Pass `false` to schedule
 *   the produce as a fire-and-forget side effect instead - the pipeline does not
 *   block on the ack, trading delivery certainty for lower latency.
 *
 * ## Accessing handleResults()
 *
 * `handleResults()` is available through the `messageAware()` builder method.
 * This requires the pipeline context to include the Kafka message, as result
 * handling needs access to the original message for DLQ entries.
 *
 * ```typescript
 * newChunkPipelineBuilder<T, { message: Message }>()
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
 * - `outputs`: IngestionOutputs containing DLQ, ingestion warnings, and any redirect outputs
 * - `promiseScheduler`: For scheduling async operations
 *
 * ## Required: handleSideEffects()
 *
 * After calling `handleResults()`, you **must** call `handleSideEffects()`
 * before calling `build()`. This is enforced by the builder types - the
 * `build()` method is not available until `handleSideEffects()` is called.
 *
 * ```typescript
 * newChunkPipelineBuilder<T, { message: Message }>()
 *   .pipeChunk(processStep())
 *   .messageAware((builder) => builder)
 *   .handleResults(config)
 *   .handleSideEffects(promiseScheduler, { await: true })  // Required!
 *   .build()
 * ```
 */
import { Message } from 'node-rdkafka'

import { DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT, OVERFLOW_OUTPUT } from '~/common/outputs'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { newChunkPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import {
    PipelineResult,
    dlq,
    drop,
    isDlqResult,
    isDropResult,
    isRedirectResult,
    ok,
    redirect,
} from '~/ingestion/framework/results'
import { createTestMessage } from '~/tests/helpers/kafka-message'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'

type BatchProcessingStep<T, U, R extends string = never> = (values: T[]) => Promise<PipelineResult<U, R>[]>

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
        const mockOutputs = createMockIngestionOutputs<
            typeof DLQ_OUTPUT | typeof OVERFLOW_OUTPUT | typeof INGESTION_WARNINGS_OUTPUT
        >()

        const promiseScheduler = new PromiseScheduler()

        const pipelineConfig = {
            outputs: mockOutputs,
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

        const pipeline = newChunkPipelineBuilder<Event, { message: Message }>()
            .pipeChunk(createValidationStep())
            .messageAware((builder) => builder)
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const message = createTestMessage()
        const batch = [createOkContext({ data: 'invalid' }, { message })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        // Result is marked as DLQ
        expect(results).toHaveLength(1)
        expect(isDlqResult(results![0].result)).toBe(true)

        // Message was sent to DLQ output with all expected fields
        expect(mockOutputs.produce).toHaveBeenCalledTimes(1)
        expect(mockOutputs.produce).toHaveBeenCalledWith(
            DLQ_OUTPUT,
            expect.objectContaining({
                value: message.value,
                key: message.key,
                headers: expect.objectContaining({
                    dlq_reason: 'Invalid data format',
                    dlq_step: 'validationStep',
                }),
            })
        )
        const dlqMessage = mockOutputs.produce.mock.calls[0][1]
        expect(dlqMessage.headers!['dlq_timestamp']).toBeDefined()
    })

    /**
     * DROP results silently discard items without sending them anywhere.
     * This is useful for filtering out items that don't need processing
     * (e.g., internal events, duplicates, or items outside scope).
     */
    it('DROP discards items without sending to Kafka', async () => {
        const mockOutputs = createMockIngestionOutputs<
            typeof DLQ_OUTPUT | typeof OVERFLOW_OUTPUT | typeof INGESTION_WARNINGS_OUTPUT
        >()

        const promiseScheduler = new PromiseScheduler()

        const pipelineConfig = {
            outputs: mockOutputs,
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

        const pipeline = newChunkPipelineBuilder<Event, { message: Message }>()
            .pipeChunk(createFilterStep())
            .messageAware((builder) => builder)
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const message = createTestMessage()
        const batch = [createOkContext({ eventType: 'internal-heartbeat' }, { message })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        // Result is marked as DROP
        expect(results).toHaveLength(1)
        expect(isDropResult(results![0].result)).toBe(true)

        // No produce calls for dropped messages
        expect(mockOutputs.produce).not.toHaveBeenCalled()
    })

    /**
     * REDIRECT results send items to a named output for alternative processing.
     * Each redirect targets a specific output (e.g. overflow, high-priority)
     * which is resolved to a Kafka topic and producer at runtime. The original
     * message key is preserved by default (`preserveKey` defaults to `true`);
     * pass `false` to discard it and let the broker assign a partition.
     */
    it('REDIRECT sends items to a named output with optional key preservation', async () => {
        const promiseScheduler = new PromiseScheduler()

        const HIGH_PRIORITY_OUTPUT = 'high_priority' as const
        const BROADCAST_OUTPUT = 'broadcast' as const

        const mockOutputs = createMockIngestionOutputs<
            typeof DLQ_OUTPUT | typeof HIGH_PRIORITY_OUTPUT | typeof BROADCAST_OUTPUT | typeof INGESTION_WARNINGS_OUTPUT
        >()

        const pipelineConfig = {
            outputs: mockOutputs,
            promiseScheduler: promiseScheduler,
        }

        interface Event {
            priority: string
        }

        function createRoutingStep(): BatchProcessingStep<Event, Event, 'high_priority' | 'broadcast'> {
            return function routingStep(items) {
                return Promise.resolve(
                    items.map((item) => {
                        if (item.priority === 'high') {
                            return redirect('High priority routing', HIGH_PRIORITY_OUTPUT, true) // preserveKey = true
                        } else if (item.priority === 'broadcast') {
                            return redirect('Broadcast routing', BROADCAST_OUTPUT, false) // preserveKey = false
                        }
                        return ok(item)
                    })
                )
            }
        }

        const pipeline = newChunkPipelineBuilder<Event, { message: Message }>()
            .pipeChunk(createRoutingStep())
            .messageAware((builder) => builder)
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const originalKey = Buffer.from('my-partition-key')
        const message1 = createTestMessage({ key: originalKey })
        const message2 = createTestMessage({ key: Buffer.from('another-key') })
        const batch = [
            createOkContext({ priority: 'high' }, { message: message1 }),
            createOkContext({ priority: 'broadcast' }, { message: message2 }),
        ]
        pipeline.feed(batch)

        const results = await pipeline.next()

        // Both results are marked as REDIRECT
        expect(results).toHaveLength(2)
        expect(isRedirectResult(results![0].result)).toBe(true)
        expect(isRedirectResult(results![1].result)).toBe(true)

        // Two messages were produced
        expect(mockOutputs.produce).toHaveBeenCalledTimes(2)

        // First message: key preserved, sent to high_priority output
        expect(mockOutputs.produce).toHaveBeenCalledWith(
            HIGH_PRIORITY_OUTPUT,
            expect.objectContaining({
                value: message1.value,
                key: originalKey,
                headers: expect.objectContaining({
                    'redirect-step': 'routingStep',
                }),
            })
        )
        const preservedKeyMessage = mockOutputs.produce.mock.calls[0][1]
        expect(preservedKeyMessage.headers!['redirect-timestamp']).toBeDefined()

        // Second message: key discarded, sent to broadcast output
        expect(mockOutputs.produce).toHaveBeenCalledWith(
            BROADCAST_OUTPUT,
            expect.objectContaining({
                value: message2.value,
                key: null,
                headers: expect.objectContaining({
                    'redirect-step': 'routingStep',
                }),
            })
        )
        const discardedKeyMessage = mockOutputs.produce.mock.calls[1][1]
        expect(discardedKeyMessage.headers!['redirect-timestamp']).toBeDefined()
    })

    /**
     * `awaitAck` (default `true`) makes result handling wait for the broker to
     * acknowledge the redirected produce before `next()` resolves. This is the
     * safe default: the item is not considered handled until it is durably
     * accepted downstream.
     *
     * Here the mocked produce never acknowledges, so `next()` stays pending
     * until the ack resolves.
     */
    it('REDIRECT with awaitAck=true blocks on the produce ack (default)', async () => {
        const promiseScheduler = new PromiseScheduler()
        const OVERFLOW = 'overflow' as const

        const mockOutputs = createMockIngestionOutputs<
            typeof DLQ_OUTPUT | typeof OVERFLOW | typeof INGESTION_WARNINGS_OUTPUT
        >()

        // Produce that only acknowledges when we resolve it by hand
        let ackResolve: () => void
        const ack = new Promise<void>((resolve) => {
            ackResolve = resolve
        })
        mockOutputs.produce.mockReturnValue(ack)

        function createRoutingStep(): BatchProcessingStep<{ v: string }, { v: string }, 'overflow'> {
            return function routingStep(items) {
                // awaitAck defaults to true (fourth arg omitted)
                return Promise.resolve(items.map(() => redirect('Overflow', OVERFLOW, true)))
            }
        }

        // await: true so the redirect side effect (the produce) is awaited before next() resolves
        const pipeline = newChunkPipelineBuilder<{ v: string }, { message: Message }>()
            .pipeChunk(createRoutingStep())
            .messageAware((builder) => builder)
            .handleResults({ outputs: mockOutputs, promiseScheduler })
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        pipeline.feed([createOkContext({ v: 'x' }, { message: createTestMessage() })])

        let resolved = false
        const nextPromise = pipeline.next().then((r) => {
            resolved = true
            return r
        })

        // Flush pending microtasks/macrotasks; next() is still blocked on the ack
        await new Promise((resolve) => setImmediate(resolve))
        expect(resolved).toBe(false)

        // Once the broker acks, next() resolves
        ackResolve!()
        const results = await nextPromise
        expect(resolved).toBe(true)
        expect(isRedirectResult(results![0].result)).toBe(true)
    })

    /**
     * `awaitAck=false` schedules the produce as a fire-and-forget side effect.
     * Result handling does not wait for the broker ack, so `next()` resolves
     * even though the produce is still in flight.
     */
    it('REDIRECT with awaitAck=false does not block on the produce ack', async () => {
        const promiseScheduler = new PromiseScheduler()
        const OVERFLOW = 'overflow' as const

        const mockOutputs = createMockIngestionOutputs<
            typeof DLQ_OUTPUT | typeof OVERFLOW | typeof INGESTION_WARNINGS_OUTPUT
        >()

        // Produce that never acknowledges within the test
        mockOutputs.produce.mockReturnValue(new Promise<void>(() => {}))

        function createRoutingStep(): BatchProcessingStep<{ v: string }, { v: string }, 'overflow'> {
            return function routingStep(items) {
                // preserveKey = true, awaitAck = false
                return Promise.resolve(items.map(() => redirect('Overflow', OVERFLOW, true, false)))
            }
        }

        // Even with await: true, the redirect side effect resolves immediately because
        // awaitAck=false means it never waits on the produce ack.
        const pipeline = newChunkPipelineBuilder<{ v: string }, { message: Message }>()
            .pipeChunk(createRoutingStep())
            .messageAware((builder) => builder)
            .handleResults({ outputs: mockOutputs, promiseScheduler })
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        pipeline.feed([createOkContext({ v: 'x' }, { message: createTestMessage() })])

        // Resolves without the pending ack (would hang if awaitAck were honored as true)
        const results = await pipeline.next()

        expect(isRedirectResult(results![0].result)).toBe(true)
        expect(mockOutputs.produce).toHaveBeenCalledTimes(1)
    })
})
