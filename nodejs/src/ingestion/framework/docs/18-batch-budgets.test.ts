/**
 * # Chapter 18: Batch Time Budgets
 *
 * Steps have no time limits of their own. Without a budget, a batch that hits
 * a slow spot runs as long as it runs, and time is enforced by the caller
 * giving up: the caller re-routes the work to another worker while this one
 * keeps processing the same messages. That is duplicate downstream work plus
 * contention exactly where the pipeline was already slow.
 *
 * A budget inverts that. Each fed batch carries a time allowance, and the
 * framework stops starting work once the allowance runs out.
 *
 * ## The budget object
 *
 * A budget enforces by virtue of existing. `BatchBudget` carries one absolute
 * deadline — `softAt` — and one flag its internal timer sets — `exhausted`; the
 * checkpoints read the flag. Past the deadline the framework stops starting
 * work; work already running finishes. It is called soft because it never
 * interrupts anything — a step that hangs forever is the consumer's ack
 * watchdog to catch, and that watchdog is the only hard limit in the system.
 *
 * `BatchBudget.unlimited()` is the no-time-policy case, and the neutral
 * element: it never exhausts, so every checkpoint is a no-op. Because it exists
 * there is no "no budget" state, and no optional-budget branch anywhere in the
 * framework.
 *
 * ## Where the budget comes from
 *
 * A budget belongs to one fed batch, so it rides the `feed()` call, and the
 * batching pipeline of chapter 14 is the interface that takes one. It stamps
 * the budget on every element of that batch, next to the messageId. The
 * argument defaults to an unlimited budget, so a caller with no time policy
 * passes nothing.
 *
 * ```ts
 * await pipeline.feed(elements, batchContext, BatchBudget.softDeadline(deadline))
 * await pipeline.feed(elements, batchContext) // unlimited
 * ```
 *
 * ## The checkpoints
 *
 * Cancellation is cooperative. JavaScript cannot preempt a running `await`, so
 * the framework never kills work; it stops dispatching it, at two checkpoints
 * it owns. Steps see nothing of the budget, and no existing step changes:
 *
 * 1. **Before each step of an element.** An exhausted element completes as
 *    `timeout('budget exceeded before <step>')`, and the rest of its chain
 *    skips through the existing non-OK short-circuit.
 * 2. **Before a chunk step.** One chunk can hold elements from several fed
 *    batches, each with its own budget, so the decision is per element:
 *    exhausted elements become timeouts and pass through, and the step runs on
 *    the remainder.
 *
 * Granularity is therefore one step. A step that runs long past the deadline
 * is not interrupted, and the retry wrappers keep retrying to their configured
 * limit, so the overrun a batch can accumulate is bounded by its slowest step
 * rather than by the deadline. `ingestion_batch_budget_overrun_seconds`
 * measures that tail.
 *
 * ## The result a budget produces
 *
 * `TIMEOUT` is the only unacked result: the message is not acked, so its
 * source redelivers it and the whole chain runs again from the top. Result
 * handling counts it and produces nothing for it, because the redelivery
 * produces it.
 *
 * The count invariant is untouched: N messages in, N results out, and
 * `afterBatch` still runs, committing the writes of the events that did
 * finish. Within one batch, budget exhaustion is monotone, so a routing key's
 * completed events are always a prefix of its feed order.
 */
import { BatchBudget } from '~/ingestion/framework/batch-budget'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { PipelineResult, isOkResult, isTimeoutResult, ok } from '~/ingestion/framework/results'

interface Event {
    key: string
    seq: number
}

type NoCtx = Record<string, never>

/** Reads the result kinds in feed order, which is how a batch's elements come back. */
function resultKinds<T>(results: { result: PipelineResult<T> }[]): string[] {
    return results.map((element) => {
        if (isOkResult(element.result)) {
            return 'ok'
        }
        return isTimeoutResult(element.result) ? 'timeout' : 'other'
    })
}

/** Reads the reason off each element the budget cut off, `null` for the rest. */
function timeoutReasons<T>(results: { result: PipelineResult<T> }[]): (string | null)[] {
    return results.map((element) => (isTimeoutResult(element.result) ? element.result.reason : null))
}

describe('Batch Time Budgets', () => {
    // A budget's deadline arrives on a timer, so a case that needs one to pass
    // moves the clock rather than waiting for it.
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    /**
     * The element checkpoint. A step that outlasts the batch's allowance is not
     * cancelled, but the next step never starts: that element completes as a
     * timeout naming the step it was cut off before. Every element the batch
     * had not reached yet is cut off before its first step, and everything that
     * finished before the deadline keeps its result.
     */
    it('stops each element at its next step once the budget is exhausted', async () => {
        const ran: string[] = []

        const pipeline = newBatchingPipeline<Event, Event, NoCtx>(
            (builder) =>
                builder.pipe(function passThroughBefore(input) {
                    return Promise.resolve(ok({ elements: input.elements, batchContext: input.batchContext }))
                }),
            (builder) =>
                builder.sequentially((steps) =>
                    steps
                        .pipe(function enrichStep(event: Event) {
                            ran.push(`enrich-${event.seq}`)
                            if (event.seq === 2) {
                                // Stands in for this step outlasting what the batch had left.
                                jest.advanceTimersByTime(1000)
                            }
                            return Promise.resolve(ok(event))
                        })
                        .pipe(function emitStep(event: Event) {
                            ran.push(`emit-${event.seq}`)
                            return Promise.resolve(ok(event))
                        })
                ),
            (builder) =>
                builder.pipe(function passThroughAfter(input) {
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: 1 }
        )

        await pipeline.feed(
            [1, 2, 3].map((seq) => createOkContext<Event, NoCtx>({ key: 'a', seq }, {})),
            {},
            BatchBudget.softDeadline(Date.now() + 1000)
        )
        const batch = await pipeline.next()

        // The first event finished; the second lost its budget mid-chain, so
        // emitStep never ran for it or for the third.
        expect(ran).toEqual(['enrich-1', 'emit-1', 'enrich-2'])
        expect(resultKinds(batch!.elements)).toEqual(['ok', 'timeout', 'timeout'])
        expect(timeoutReasons(batch!.elements)).toEqual([
            null,
            'budget exceeded before emitStep',
            'budget exceeded before enrichStep',
        ])
    })

    /**
     * The chunk checkpoint. Batches run concurrently, so one chunk can hold
     * elements from several of them, each with its own budget. The step runs
     * for the elements whose batch still has time, and each batch's results
     * reflect only its own budget.
     */
    it('runs a chunk step on the elements whose batch still has time', async () => {
        const chunked: number[][] = []

        const pipeline = newBatchingPipeline<Event, Event, NoCtx>(
            (builder) =>
                builder.pipe(function passThroughBefore(input) {
                    return Promise.resolve(ok({ elements: input.elements, batchContext: input.batchContext }))
                }),
            (builder) =>
                builder.pipeChunk(function writeChunk(events: Event[]) {
                    chunked.push(events.map((event) => event.seq))
                    return Promise.resolve(events.map((event) => ok(event)))
                }),
            (builder) =>
                builder.pipe(function passThroughAfter(input) {
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: 2 }
        )

        // Both batches are in flight before either drains, so their elements
        // meet in one chunk.
        await pipeline.feed(
            [createOkContext<Event, NoCtx>({ key: 'a', seq: 1 }, {})],
            {},
            BatchBudget.softDeadline(Date.now() - 1)
        )
        await pipeline.feed(
            [createOkContext<Event, NoCtx>({ key: 'b', seq: 2 }, {})],
            {},
            BatchBudget.softDeadline(Date.now() + 60_000)
        )
        const spentBatch = await pipeline.next()
        const freshBatch = await pipeline.next()

        // The step saw only the element whose batch still had time.
        expect(chunked).toEqual([[2]])
        expect(resultKinds(spentBatch!.elements)).toEqual(['timeout'])
        expect(timeoutReasons(spentBatch!.elements)).toEqual(['budget exceeded before writeChunk'])
        expect(resultKinds(freshBatch!.elements)).toEqual(['ok'])
    })

    /**
     * The count invariant under expiry. A budget that is already spent when the
     * batch is fed cancels every element, and the batch still returns one
     * result per message and still runs its afterBatch hook — which is what
     * commits the writes of the events that did finish.
     */
    it('returns one result per message and still runs afterBatch when everything times out', async () => {
        let flushedElements = 0

        const pipeline = newBatchingPipeline<Event, Event, NoCtx>(
            (builder) =>
                builder.pipe(function passThroughBefore(input) {
                    return Promise.resolve(ok({ elements: input.elements, batchContext: input.batchContext }))
                }),
            (builder) =>
                builder.sequentially((steps) =>
                    steps.pipe(function emitStep(event: Event) {
                        return Promise.resolve(ok(event))
                    })
                ),
            (builder) =>
                builder.pipe(function flushBatch(input) {
                    flushedElements = input.elements.length
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: 1 }
        )

        await pipeline.feed(
            [
                { key: 'a', seq: 1 },
                { key: 'a', seq: 2 },
                { key: 'b', seq: 1 },
            ].map((event) => createOkContext<Event, NoCtx>(event, {})),
            {},
            BatchBudget.softDeadline(Date.now() - 1)
        )
        const batch = await pipeline.next()

        expect(batch!.elements).toHaveLength(3)
        expect(resultKinds(batch!.elements)).toEqual(['timeout', 'timeout', 'timeout'])
        expect(flushedElements).toBe(3)
    })

    /**
     * The prefix property. Within one batch the budget expires once and never
     * comes back, so a routing key's completed events are always a prefix of
     * its feed order. That is what makes redelivering the remainder safe: the
     * redelivery resumes where the batch stopped, with no gap in the middle.
     */
    it('completes a prefix of each key’s feed order', async () => {
        const processed: number[] = []

        const pipeline = newBatchingPipeline<Event, Event, NoCtx>(
            (builder) =>
                builder.pipe(function passThroughBefore(input) {
                    return Promise.resolve(ok({ elements: input.elements, batchContext: input.batchContext }))
                }),
            (builder) =>
                builder.concurrentlyPerGroup(
                    (event: Event) => event.key,
                    (group) =>
                        group.sequentially((steps) =>
                            steps.pipe(function processStep(event: Event) {
                                processed.push(event.seq)
                                if (processed.length === 2) {
                                    // Stands in for the second event exhausting the batch's time.
                                    jest.advanceTimersByTime(1000)
                                }
                                return Promise.resolve(ok(event))
                            })
                        )
                ),
            (builder) =>
                builder.pipe(function passThroughAfter(input) {
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: 1 }
        )

        await pipeline.feed(
            [1, 2, 3, 4].map((seq) => createOkContext<Event, NoCtx>({ key: 'a', seq }, {})),
            {},
            BatchBudget.softDeadline(Date.now() + 1000)
        )
        const batch = await pipeline.next()

        expect(processed).toEqual([1, 2])
        expect(resultKinds(batch!.elements)).toEqual(['ok', 'ok', 'timeout', 'timeout'])
    })

    /**
     * The neutral element. A caller with no time policy passes no budget at
     * all, and nothing about the batch's behavior changes.
     */
    it('never cancels anything under the default unlimited budget', async () => {
        const pipeline = newBatchingPipeline<Event, Event, NoCtx>(
            (builder) =>
                builder.pipe(function passThroughBefore(input) {
                    return Promise.resolve(ok({ elements: input.elements, batchContext: input.batchContext }))
                }),
            (builder) =>
                builder.sequentially((steps) =>
                    steps.pipe(function emitStep(event: Event) {
                        return Promise.resolve(ok(event))
                    })
                ),
            (builder) =>
                builder.pipe(function passThroughAfter(input) {
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: 1 }
        )

        await pipeline.feed(
            [{ key: 'a', seq: 1 }].map((event) => createOkContext<Event, NoCtx>(event, {})),
            {}
        )
        const batch = await pipeline.next()

        expect(resultKinds(batch!.elements)).toEqual(['ok'])
    })
})
