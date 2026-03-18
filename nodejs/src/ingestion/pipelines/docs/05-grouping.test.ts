/**
 * # Chapter 5: Grouped Processing
 *
 * The `groupBy()` method partitions items by a key. It must be followed by
 * `concurrently()`, which processes each group as a separate stream.
 *
 * ## Ordering Guarantees
 *
 * **Important:** Items are NOT returned in the original input order. Groups
 * complete independently and are returned as each group finishes. A faster
 * group will return before a slower group, regardless of input order.
 *
 * What grouping DOES guarantee:
 * - Items within the same group maintain their relative input order
 * - Using `sequentially()` inside the group ensures items are processed one
 *   at a time, preserving order within that group
 *
 * ## How It Works
 *
 * ```
 * .groupBy(keyFn)
 * .concurrently((groupBuilder) => groupBuilder.sequentially(...))
 * ```
 *
 * - `groupBy()` partitions items by key
 * - `concurrently()` processes groups in parallel (groups return as they complete)
 * - `sequentially()` inside ensures within-group order is preserved
 *
 * ## Real-World Use Cases
 *
 * - Person operations: All updates to a person must be ordered
 * - Team-scoped processing: Teams can be processed in parallel
 * - User event ordering: Events for the same user maintain order
 */
import { GroupProcessingBuilder, newBatchPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { ok } from '../results'
import { ProcessingStep } from '../steps'
import { consumeAll } from './helpers'

interface Event {
    userId: string
    eventId: number
}

describe('Grouped Processing', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })
    /**
     * The `groupBy()` method partitions items by a key function. Items with
     * the same key are grouped together for ordered processing.
     *
     * Processing flow for the example below:
     *
     * ```
     * Input batch:
     *   [alice:1, bob:2, alice:3, bob:4]
     *
     * After groupBy(userId):
     *   Group "alice": [1, 3]
     *   Group "bob":   [2, 4]
     *
     * concurrently() processes groups in parallel:
     *   ┌─────────────────────────────────────┐
     *   │  Time ──────────────────────────►   │
     *   │                                     │
     *   │  alice: ─[1]────[3]─►               │
     *   │                       (sequential)  │
     *   │  bob:   ─[2]────[4]─►               │
     *   │                       (sequential)  │
     *   └─────────────────────────────────────┘
     *
     * Within each group, items process sequentially (1 before 3, 2 before 4).
     * Groups alice and bob process concurrently (in parallel).
     * ```
     */
    it('groupBy() partitions items by a key function', async () => {
        const groupsProcessed = new Map<string, number[]>()

        function createProcessEventStep(): ProcessingStep<Event, Event> {
            return async function processEventStep(event) {
                const eventIds = groupsProcessed.get(event.userId) || []
                eventIds.push(event.eventId)
                groupsProcessed.set(event.userId, eventIds)
                await new Promise((resolve) => setTimeout(resolve, 5))
                return ok(event)
            }
        }

        function createGroupPipeline(groupBuilder: GroupProcessingBuilder<Event, Event>) {
            return groupBuilder.sequentially((b) => b.pipe(createProcessEventStep()))
        }

        const pipeline = newBatchPipelineBuilder<Event>()
            .groupBy((event) => event.userId)
            .concurrently(createGroupPipeline)
            .build()

        const events: Event[] = [
            { userId: 'alice', eventId: 1 },
            { userId: 'bob', eventId: 2 },
            { userId: 'alice', eventId: 3 },
            { userId: 'bob', eventId: 4 },
        ]

        const batch = events.map((e) => createContext(ok(e)))
        pipeline.feed(batch)

        await consumeAll(pipeline, 20)

        expect(groupsProcessed.get('alice')).toEqual([1, 3])
        expect(groupsProcessed.get('bob')).toEqual([2, 4])
    })

    /**
     * Items in the same group are processed sequentially, maintaining order.
     */
    it('items in the same group are processed sequentially', async () => {
        const processedOrder: number[] = []

        function createProcessEventStep(): ProcessingStep<Event, Event> {
            return async function processEventStep(event) {
                processedOrder.push(event.eventId)
                await new Promise((resolve) => setTimeout(resolve, 10))
                return ok(event)
            }
        }

        function createGroupPipeline(groupBuilder: GroupProcessingBuilder<Event, Event>) {
            return groupBuilder.sequentially((b) => b.pipe(createProcessEventStep()))
        }

        const pipeline = newBatchPipelineBuilder<Event>()
            .groupBy((event) => event.userId)
            .concurrently(createGroupPipeline)
            .build()

        const events: Event[] = [
            { userId: 'alice', eventId: 1 },
            { userId: 'alice', eventId: 2 },
            { userId: 'alice', eventId: 3 },
        ]

        const batch = events.map((e) => createContext(ok(e)))
        pipeline.feed(batch)

        await consumeAll(pipeline, 30)

        expect(processedOrder).toEqual([1, 2, 3])
    })

    /**
     * Items in different groups can be processed concurrently, improving
     * throughput when groups are independent.
     *
     * This test uses specific delays to prove concurrency:
     * - alice: 30ms delay per event (2 events = 60ms total)
     * - bob: 10ms delay per event (2 events = 20ms total)
     * - charlie: 20ms delay per event (2 events = 40ms total)
     *
     * If sequential (input order): alice would finish first
     * If concurrent (all start together): bob finishes first, then charlie, then alice
     *
     * Each call to next() returns a complete group's results as a batch.
     */
    it('items in different groups can process concurrently', async () => {
        const delays: Record<string, number> = {
            alice: 30,
            bob: 10,
            charlie: 20,
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

        const pipeline = newBatchPipelineBuilder<Event>()
            .groupBy((event) => event.userId)
            .concurrently(createGroupPipeline)
            .build()

        const events: Event[] = [
            { userId: 'alice', eventId: 1 },
            { userId: 'bob', eventId: 2 },
            { userId: 'charlie', eventId: 3 },
            { userId: 'alice', eventId: 4 },
            { userId: 'bob', eventId: 5 },
            { userId: 'charlie', eventId: 6 },
        ]

        const batch = events.map((e) => createContext(ok(e)))
        pipeline.feed(batch)

        // Collect batches as groups complete
        const batches: string[][] = []
        const collectResults = (async () => {
            let result = await pipeline.next()
            while (result !== null) {
                batches.push(
                    result.map((r) => {
                        const event = (r.result as { value: Event }).value
                        return `${event.userId}:${event.eventId}`
                    })
                )
                result = await pipeline.next()
            }
        })()

        // Advance time for all groups to complete (60ms for alice's 2 events)
        await jest.advanceTimersByTimeAsync(60)
        await collectResults

        // Groups complete in delay order, not input order:
        // - bob (2 x 10ms = 20ms) finishes first
        // - charlie (2 x 20ms = 40ms) finishes second
        // - alice (2 x 30ms = 60ms) finishes last
        expect(batches).toEqual([
            ['bob:2', 'bob:5'],
            ['charlie:3', 'charlie:6'],
            ['alice:1', 'alice:4'],
        ])
    })

    /**
     * Complex group keys: Events are grouped by token + distinct_id.
     * This ensures ordering per-user within a project while allowing parallelism
     * across different users and projects.
     *
     * ```
     * Input events:
     *   [token-A/user-1/login, token-B/user-1/signup, token-A/user-2/pageview, token-A/user-1/purchase]
     *
     * After groupBy(token + distinct_id):
     *   Group "token-A:user-1": [login, purchase]  <- same user in same project
     *   Group "token-B:user-1": [signup]           <- different project (different group)
     *   Group "token-A:user-2": [pageview]         <- different user (different group)
     *
     * Same distinct_id with different tokens -> different groups (different projects)
     * Same token with different distinct_ids -> different groups (different users)
     * Same token + distinct_id -> same group (processed sequentially)
     * ```
     */
    it('complex group keys with token + distinct_id', async () => {
        interface IngestionEvent {
            token: string
            distinctId: string
            message: string
        }

        const groupsProcessed = new Map<string, string[]>()

        function createProcessEventStep(): ProcessingStep<IngestionEvent, IngestionEvent> {
            return async function processEventStep(event) {
                const key = `${event.token}:${event.distinctId}`
                const messages = groupsProcessed.get(key) || []
                messages.push(event.message)
                groupsProcessed.set(key, messages)
                await new Promise((resolve) => setTimeout(resolve, 5))
                return ok(event)
            }
        }

        function createGroupPipeline(groupBuilder: GroupProcessingBuilder<IngestionEvent, IngestionEvent>) {
            return groupBuilder.sequentially((b) => b.pipe(createProcessEventStep()))
        }

        const pipeline = newBatchPipelineBuilder<IngestionEvent>()
            .groupBy((event) => `${event.token}:${event.distinctId}`)
            .concurrently(createGroupPipeline)
            .build()

        const events: IngestionEvent[] = [
            // Different tokens with same distinct_id are separate groups (different projects)
            { token: 'token-A', distinctId: 'user-1', message: 'login' },
            { token: 'token-B', distinctId: 'user-1', message: 'signup' },
            // Same token with different distinct_id are separate groups (different users)
            { token: 'token-A', distinctId: 'user-2', message: 'pageview' },
            // Same token + distinct_id -> same group, processed in order
            { token: 'token-A', distinctId: 'user-1', message: 'purchase' },
        ]

        const batch = events.map((e) => createContext(ok(e)))
        pipeline.feed(batch)

        await consumeAll(pipeline, 10)

        // Same token + distinct_id -> same group, processed in order
        expect(groupsProcessed.get('token-A:user-1')).toEqual(['login', 'purchase'])

        // Same distinct_id, different token -> different groups
        expect(groupsProcessed.get('token-B:user-1')).toEqual(['signup'])

        // Same token, different distinct_id -> different groups
        expect(groupsProcessed.get('token-A:user-2')).toEqual(['pageview'])
    })
})
