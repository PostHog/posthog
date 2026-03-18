/**
 * # Chapter 8: Async Operations and Side Effects
 *
 * Side effects are async operations that are not mission critical - they
 * should happen alongside main processing but shouldn't block the pipeline.
 * If a side effect fails, the main processing result is unaffected.
 *
 * Examples include:
 *
 * - **Logging**: Writing to log systems
 * - **Metrics**: Updating counters and gauges
 * - **Notifications**: Sending alerts or webhooks
 * - **Kafka publishes**: Writing to other topics
 *
 * ## How Side Effects Work
 *
 * 1. Steps add promises to the `sideEffects` array in results
 * 2. Side effects accumulate through the pipeline
 * 3. At the end, `handleSideEffects()` processes them all
 * 4. Options: await completion or schedule for background execution
 *
 * ## Why Not Just Await Inline?
 *
 * - **Performance**: Side effects can run in parallel with processing
 * - **Decoupling**: Main processing doesn't depend on side effect success
 * - **Batching**: Side effects can be batched for efficiency
 */
import { PromiseScheduler } from '../../../utils/promise-scheduler'
import { newBatchPipelineBuilder, newPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { PipelineResult, isOkResult, ok } from '../results'
import { ProcessingStep } from '../steps'

type BatchProcessingStep<T, U> = (values: T[]) => Promise<PipelineResult<U>[]>

describe('Side Effects Basics', () => {
    /**
     * Steps can add side effects to results using the second parameter
     * of the `ok()` function (array of promises).
     */
    it('steps can add side effects to context', async () => {
        const logCalls: string[] = []

        function logSideEffect(message: string): Promise<void> {
            return new Promise((resolve) => {
                logCalls.push(message)
                resolve()
            })
        }

        interface Input {
            value: string
        }

        interface Output {
            value: string
            processed: boolean
        }

        function createProcessWithLoggingStep(): ProcessingStep<Input, Output> {
            return function processWithLoggingStep(input) {
                const result = input.value.toUpperCase()
                const sideEffect = logSideEffect(`Processed: ${input.value} -> ${result}`)
                return Promise.resolve(ok({ value: result, processed: true }, [sideEffect]))
            }
        }

        const pipeline = newPipelineBuilder<Input>().pipe(createProcessWithLoggingStep()).build()

        const result = await pipeline.process(createContext(ok({ value: 'hello' })))

        expect(isOkResult(result.result)).toBe(true)

        // Side effect is stored in context
        expect(result.context.sideEffects).toHaveLength(1)

        // Side effect has already started executing
        await Promise.all(result.context.sideEffects)
        expect(logCalls).toContain('Processed: hello -> HELLO')
    })

    /**
     * Side effects accumulate through the pipeline - each step can add
     * its own side effects and they're all collected.
     */
    it('side effects accumulate through the pipeline', async () => {
        const auditLog: string[] = []

        interface Input {
            value: number
        }

        function createStep1(): ProcessingStep<Input, Input> {
            return function step1(input) {
                const effect = Promise.resolve().then(() => auditLog.push('step1 completed'))
                return Promise.resolve(ok({ value: input.value * 2 }, [effect]))
            }
        }

        function createStep2(): ProcessingStep<Input, Input> {
            return function step2(input) {
                const effect = Promise.resolve().then(() => auditLog.push('step2 completed'))
                return Promise.resolve(ok({ value: input.value + 10 }, [effect]))
            }
        }

        function createStep3(): ProcessingStep<Input, Input> {
            return function step3(input) {
                const effect = Promise.resolve().then(() => auditLog.push('step3 completed'))
                return Promise.resolve(ok({ value: input.value * input.value }, [effect]))
            }
        }

        const pipeline = newPipelineBuilder<Input>().pipe(createStep1()).pipe(createStep2()).pipe(createStep3()).build()

        const result = await pipeline.process(createContext(ok({ value: 5 })))

        // All three side effects are collected
        expect(result.context.sideEffects).toHaveLength(3)

        // Wait for all side effects
        await Promise.all(result.context.sideEffects)

        // All steps logged their completion
        expect(auditLog).toHaveLength(3)
        expect(auditLog).toContain('step1 completed')
        expect(auditLog).toContain('step2 completed')
        expect(auditLog).toContain('step3 completed')
    })

    /**
     * A single step can add multiple independent side effects.
     */
    it('a step can add multiple side effects', async () => {
        const notifications: string[] = []
        const analytics: string[] = []
        const cache: string[] = []

        interface Event {
            type: string
            userId: string
        }

        function createProcessEventStep(): ProcessingStep<Event, Event & { handled: boolean }> {
            return function processEventStep(event) {
                const notifyEffect = Promise.resolve().then(() => {
                    notifications.push(`Notify: ${event.type} for ${event.userId}`)
                })

                const analyticsEffect = Promise.resolve().then(() => {
                    analytics.push(`Track: ${event.type}`)
                })

                const cacheEffect = Promise.resolve().then(() => {
                    cache.push(`Cache: ${event.userId}`)
                })

                return Promise.resolve(ok({ ...event, handled: true }, [notifyEffect, analyticsEffect, cacheEffect]))
            }
        }

        const pipeline = newPipelineBuilder<Event>().pipe(createProcessEventStep()).build()

        const result = await pipeline.process(createContext(ok({ type: 'purchase', userId: 'user-1' })))

        // Three side effects registered
        expect(result.context.sideEffects).toHaveLength(3)

        await Promise.all(result.context.sideEffects)

        expect(notifications).toHaveLength(1)
        expect(analytics).toHaveLength(1)
        expect(cache).toHaveLength(1)
    })
})

describe('Handling Side Effects', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    /**
     * ## `await: true` - Blocking Side Effects
     *
     * With `await: true`, `handleSideEffects()` blocks until all accumulated
     * side effects complete. Steps that return side effects do NOT block - they
     * just register promises. The blocking only happens when `handleSideEffects()`
     * is called with `await: true`.
     *
     * This is the simpler model with stronger guarantees:
     *
     * - **Blocking**: `handleSideEffects()` waits for all side effects before returning
     * - **Error visibility**: Errors in side effects will cause the pipeline
     *   to throw, allowing the caller to handle them (e.g., retry the batch)
     * - **Ordering**: Side effects complete before the next batch starts
     *
     * Use `await: true` when:
     * - Side effects are relatively fast
     * - You need confirmation that side effects completed
     * - You want errors to surface immediately
     */
    it('handleSideEffects with await: true blocks until completion', async () => {
        const completedEffects: string[] = []
        const promiseScheduler = new PromiseScheduler()

        interface Item {
            id: string
        }

        function createProcessStep(): ProcessingStep<Item, Item> {
            return function processStep(input) {
                const effect = new Promise<void>((resolve) => {
                    setTimeout(() => {
                        completedEffects.push(input.id)
                        resolve()
                    }, 10)
                })
                return Promise.resolve(ok({ id: input.id }, [effect]))
            }
        }

        function createBatchProcessStep(): BatchProcessingStep<Item, Item> {
            return async function batchProcessStep(items) {
                return Promise.all(items.map((item) => createProcessStep()(item)))
            }
        }

        const pipeline = newBatchPipelineBuilder<Item>()
            .pipeBatch(createBatchProcessStep())
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const items = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
        const batch = items.map((item) => createContext(ok(item)))
        pipeline.feed(batch)

        const nextPromise = pipeline.next()
        await jest.advanceTimersByTimeAsync(10)
        await nextPromise

        // With await: true, all side effects have completed
        expect(completedEffects.sort()).toEqual(['a', 'b', 'c'])
    })

    /**
     * ## `await: false` - Background Side Effects
     *
     * With `await: false`, `handleSideEffects()` registers accumulated side effects
     * with the PromiseScheduler and returns immediately without waiting. Steps that
     * return side effects never block - they just register promises that are later
     * handled by `handleSideEffects()`.
     *
     * **Key characteristics:**
     *
     * - **Non-blocking**: Pipeline returns immediately, side effects run in background
     * - **Best-effort**: Side effect failures don't affect pipeline results
     * - **Basic error handling**: Errors are logged but not propagated to the caller
     *
     * **PromiseScheduler lifecycle:**
     *
     * When using `await: false`, the caller is responsible for awaiting the
     * PromiseScheduler at appropriate points:
     *
     * - **End of batch**: Call `promiseScheduler.waitForAll()` after processing
     *   each batch to ensure side effects complete before committing offsets
     * - **Rebalancing**: Await pending side effects before releasing partitions
     *   to avoid losing in-flight DLQ/redirect messages
     * - **Process shutdown**: Drain the scheduler during graceful shutdown to
     *   complete pending side effects before the process exits
     *
     * **Trade-offs:**
     *
     * - Higher throughput (pipeline doesn't wait for side effects)
     * - Side effects may be lost if the process crashes before they complete
     * - DLQ and redirect operations are "best-effort" - failures are logged
     *   but the original message is still considered processed
     *
     * Use `await: false` when:
     * - Side effects are slow (e.g., network calls to external systems)
     * - Throughput is more important than guaranteed delivery of side effects
     * - You have proper lifecycle management for the PromiseScheduler
     */
    it('handleSideEffects with await: false schedules for background execution', async () => {
        const completedEffects: string[] = []
        const promiseScheduler = new PromiseScheduler()

        interface Item {
            id: string
        }

        function createProcessStep(): ProcessingStep<Item, Item> {
            return function processStep(input) {
                const effect = new Promise<void>((resolve) => {
                    setTimeout(() => {
                        completedEffects.push(input.id)
                        resolve()
                    }, 50)
                })
                return Promise.resolve(ok({ id: input.id }, [effect]))
            }
        }

        function createBatchProcessStep(): BatchProcessingStep<Item, Item> {
            return async function batchProcessStep(items) {
                return Promise.all(items.map((item) => createProcessStep()(item)))
            }
        }

        const pipeline = newBatchPipelineBuilder<Item>()
            .pipeBatch(createBatchProcessStep())
            .handleSideEffects(promiseScheduler, { await: false })
            .build()

        const items = [{ id: 'x' }, { id: 'y' }]
        const batch = items.map((item) => createContext(ok(item)))
        pipeline.feed(batch)

        await pipeline.next()

        // Side effects have NOT completed yet - they're running in background
        expect(completedEffects).toEqual([])

        // Advance timers and wait for scheduler to complete
        await jest.advanceTimersByTimeAsync(50)
        await promiseScheduler.waitForAll()

        // Now side effects have completed
        expect(completedEffects.sort()).toEqual(['x', 'y'])
    })
})
