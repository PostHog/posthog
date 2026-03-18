/**
 * # Chapter 6: Gathering Results
 *
 * The `gather()` method collects all results from a streaming pipeline into
 * a single batch. This is useful when you need all results together before
 * continuing to the next step.
 *
 * ## When to Use gather()
 *
 * - After `concurrently()`: collect all concurrent results into one batch
 * - After `groupBy().concurrently()`: collect all group results into one batch
 *
 * ## How gather() Works
 *
 * Without gather(), pipelines stream results as they become available:
 * - `concurrently()` returns items one at a time (in input order)
 * - `groupBy().concurrently()` returns groups one at a time as each completes
 *
 * With gather(), all results are collected and returned in a single batch.
 */
import { GroupProcessingBuilder, newBatchPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { ok } from '../results'
import { ProcessingStep } from '../steps'
import { collectBatches } from './helpers'

interface Event {
    userId: string
    eventId: number
}

describe('Gathering Results', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    /**
     * Without gather(), concurrently() returns items one at a time.
     * With gather(), all items are collected into a single batch.
     * In both cases, input order is preserved.
     *
     * This test uses variable delays to demonstrate ordering:
     * - Item 1: 30ms delay (finishes last)
     * - Item 2: 10ms delay (finishes first)
     * - Item 3: 20ms delay (finishes second)
     */
    it('gather() after concurrently() collects items into one batch', async () => {
        const delays: Record<number, number> = { 1: 30, 2: 10, 3: 20 }

        function createVariableDelayStep(): ProcessingStep<number, number> {
            return async function variableDelayStep(n) {
                await new Promise((resolve) => setTimeout(resolve, delays[n]))
                return ok(n * 10)
            }
        }

        // Without gather: items stream one at a time in input order
        const streamingPipeline = newBatchPipelineBuilder<number>()
            .concurrently((builder) => builder.pipe(createVariableDelayStep()))
            .build()

        streamingPipeline.feed([1, 2, 3].map((n) => createContext(ok(n))))
        const streamingPromise = collectBatches(streamingPipeline)
        await jest.advanceTimersByTimeAsync(30)
        const streamingBatches = await streamingPromise

        // Without gather: 3 separate batches, one item each, in input order
        expect(streamingBatches).toEqual([[10], [20], [30]])

        // With gather: all items collected into one batch
        const gatheringPipeline = newBatchPipelineBuilder<number>()
            .concurrently((builder) => builder.pipe(createVariableDelayStep()))
            .gather()
            .build()

        gatheringPipeline.feed([1, 2, 3].map((n) => createContext(ok(n))))
        const gatheringPromise = collectBatches(gatheringPipeline)
        await jest.advanceTimersByTimeAsync(30)
        const gatheringBatches = await gatheringPromise

        // With gather: one batch with all items, input order preserved
        expect(gatheringBatches).toEqual([[10, 20, 30]])
    })

    /**
     * Without gather(), groupBy().concurrently() returns groups one at a time
     * as each group completes. With gather(), all groups are collected into
     * a single batch.
     *
     * Within each group, events are always processed sequentially (order preserved).
     */
    it('gather() after groupBy().concurrently() collects groups into one batch', async () => {
        const delays: Record<string, number> = {
            alice: 30,
            bob: 10,
        }

        function createVariableDelayStep(): ProcessingStep<Event, Event> {
            return async function variableDelayStep(event) {
                await new Promise((resolve) => setTimeout(resolve, delays[event.userId]))
                return ok(event)
            }
        }

        function createGroupPipeline(groupBuilder: GroupProcessingBuilder<Event, Event>) {
            return groupBuilder.sequentially((b) => b.pipe(createVariableDelayStep()))
        }

        // Input order: alice:1, bob:2, alice:3, bob:4
        const events: Event[] = [
            { userId: 'alice', eventId: 1 },
            { userId: 'bob', eventId: 2 },
            { userId: 'alice', eventId: 3 },
            { userId: 'bob', eventId: 4 },
        ]

        // Without gather: groups stream one at a time in completion order
        const streamingPipeline = newBatchPipelineBuilder<Event>()
            .groupBy((event) => event.userId)
            .concurrently(createGroupPipeline)
            .build()

        streamingPipeline.feed(events.map((e) => createContext(ok(e))))
        // bob: 2 events x 10ms = 20ms, alice: 2 events x 30ms = 60ms
        const streamingPromise = collectBatches(streamingPipeline)
        await jest.advanceTimersByTimeAsync(60)
        const streamingBatches = await streamingPromise

        // Without gather: bob's group finishes first, then alice's
        // Within each group, events are in order (2 before 4, 1 before 3)
        expect(streamingBatches).toEqual([
            [
                { userId: 'bob', eventId: 2 },
                { userId: 'bob', eventId: 4 },
            ],
            [
                { userId: 'alice', eventId: 1 },
                { userId: 'alice', eventId: 3 },
            ],
        ])

        // With gather: all groups collected into one batch
        const gatheringPipeline = newBatchPipelineBuilder<Event>()
            .groupBy((event) => event.userId)
            .concurrently(createGroupPipeline)
            .gather()
            .build()

        gatheringPipeline.feed(events.map((e) => createContext(ok(e))))
        const gatheringPromise = collectBatches(gatheringPipeline)
        await jest.advanceTimersByTimeAsync(60)
        const gatheringBatches = await gatheringPromise

        // With gather: one batch with all items
        // Groups are in completion order (bob first), within-group order preserved
        expect(gatheringBatches).toEqual([
            [
                { userId: 'bob', eventId: 2 },
                { userId: 'bob', eventId: 4 },
                { userId: 'alice', eventId: 1 },
                { userId: 'alice', eventId: 3 },
            ],
        ])
    })
})
