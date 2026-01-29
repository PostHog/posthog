/**
 * # Chapter 12: Filter and Map Pattern
 *
 * The `filterOk()` and `map()` combination is a common pattern for transforming
 * pipeline results and enriching context. This is especially useful when you need
 * to extract data from results and add it to the context for downstream processing.
 *
 * ## Common Use Case: Adding Team to Context
 *
 * Many pipeline operations are team-scoped (like `teamAware()` and
 * `handleIngestionWarnings()`). These methods require `team` to be present in the
 * pipeline context - if it's not, the code will not compile.
 *
 * When team data comes from a lookup step, `filterOk()` and `map()` allow us to
 * add the team to context in a type-safe way:
 *
 * 1. Filter out failed lookups with `filterOk()`
 * 2. Extract team from the result and add to context with `map()`
 * 3. Use `teamAware()` for team-scoped operations
 */
import { Message } from 'node-rdkafka'

import { createTestMessage } from '../../../../tests/helpers/kafka-message'
import { createTestTeam } from '../../../../tests/helpers/team'
import { Team } from '../../../types'
import { PromiseScheduler } from '../../../utils/promise-scheduler'
import { newBatchPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { PipelineWarning } from '../pipeline.interface'
import { PipelineResult, dlq, isOkResult, ok, redirect } from '../results'

type BatchProcessingStep<T, U> = (values: T[]) => Promise<PipelineResult<U>[]>

describe('Filter and Map', () => {
    /**
     * The `teamAware()` method requires `{ team: Team }` in the pipeline context.
     * Without it, TypeScript will report a compile error.
     *
     * This pattern uses `filterOk()` to remove failed results, then `map()` to
     * extract team from the result value and add it to context in a type-safe way.
     */
    it('filterOk and map enable team-aware processing', async () => {
        const processedEvents: Array<{ eventName: string; teamId: number }> = []
        const producedMessages: any[] = []
        const promiseScheduler = new PromiseScheduler()
        const mockKafkaProducer = {
            produce: jest.fn((msg) => {
                producedMessages.push(msg)
                return Promise.resolve()
            }),
            queueMessages: jest.fn((msg) => {
                producedMessages.push(msg)
                return Promise.resolve()
            }),
        }
        const pipelineConfig = {
            kafkaProducer: mockKafkaProducer as any,
            dlqTopic: 'test-dlq',
            promiseScheduler,
        }

        interface RawEvent {
            teamId: number
            name: string
        }

        interface EventWithTeam {
            event: RawEvent
            team: Team
        }

        // Step 1: Resolve team from teamId (some lookups may fail)
        function createTeamLookupStep(): BatchProcessingStep<RawEvent, EventWithTeam> {
            return function teamLookupStep(events) {
                return Promise.resolve(
                    events.map((event) => {
                        if (event.teamId === 999) {
                            return dlq('Team not found', new Error('Unknown team'))
                        }
                        return ok({
                            event,
                            team: createTestTeam({ id: event.teamId }),
                        })
                    })
                )
            }
        }

        // Step 2: Process event (runs within teamAware context)
        function createProcessEventStep(): BatchProcessingStep<EventWithTeam, EventWithTeam> {
            return function processEventStep(events) {
                return Promise.resolve(
                    events.map((item) => {
                        // Redirect special events to overflow topic
                        if (item.event.name === 'overflow') {
                            return redirect('Event overflow', 'overflow-topic')
                        }

                        // Add warning for deprecated events
                        const warnings: PipelineWarning[] = []
                        if (item.event.name === 'deprecated_event') {
                            warnings.push({
                                type: 'deprecated_event',
                                details: { eventName: item.event.name },
                            })
                        }

                        processedEvents.push({
                            eventName: item.event.name,
                            teamId: item.team.id,
                        })
                        return ok(item, [], warnings)
                    })
                )
            }
        }

        // Note: This pipeline structure is a bit convoluted because filterOk() and map()
        // drop non-OK items. This will be refactored to a filterMap() step that passes
        // through non-OK results, so handleResults/handleSideEffects will only need to
        // be called once at the end.
        const pipeline = newBatchPipelineBuilder<RawEvent, { message: Message }>()
            .pipeBatch(createTeamLookupStep())
            // Handle results and side effects BEFORE filterOk - DLQ items
            // won't be processed after filterOk removes them
            .messageAware((builder) => builder)
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: true })
            // filterOk() removes non-OK results (failed team lookups)
            .filterOk()
            // map() extracts team from result and adds to context
            .map((element) => ({
                result: element.result,
                context: {
                    ...element.context,
                    team: element.result.value.team,
                },
            }))
            // teamAware() now works because context has team
            // Wrap with messageAware to get access to handleResults after handleIngestionWarnings
            .messageAware((builder) =>
                builder
                    .teamAware((b) => b.pipeBatch(createProcessEventStep()))
                    .handleIngestionWarnings(mockKafkaProducer as any)
            )
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const batch = [
            createContext(ok<RawEvent>({ teamId: 1, name: 'pageview' }), { message: createTestMessage() }),
            createContext(ok<RawEvent>({ teamId: 999, name: 'will_fail' }), { message: createTestMessage() }),
            createContext(ok<RawEvent>({ teamId: 2, name: 'overflow' }), { message: createTestMessage() }),
            createContext(ok<RawEvent>({ teamId: 3, name: 'deprecated_event' }), { message: createTestMessage() }),
        ]
        // Type assertion needed because team is added dynamically via map()
        pipeline.feed(batch as any)

        const results = await pipeline.next()

        // 3 results returned (one DLQ'd before filterOk, one redirected, two OK)
        expect(results).toHaveLength(3)

        // Two events are OK (pageview and deprecated_event), one was redirected
        const okResults = results!.filter((r) => isOkResult(r.result))
        expect(okResults).toHaveLength(2)

        // Verify the pageview and deprecated events were processed
        expect(processedEvents).toEqual([
            { eventName: 'pageview', teamId: 1 },
            { eventName: 'deprecated_event', teamId: 3 },
        ])

        // Verify Kafka producer was called for DLQ, redirect, and ingestion warning
        const topics = producedMessages.map((msg) => msg.topic)

        // DLQ was called for the team lookup failure
        expect(topics).toContain('test-dlq')

        // Redirect was called for the overflow event
        expect(topics).toContain('overflow-topic')

        // Ingestion warning was produced for deprecated event
        const warningTopics = topics.filter((t: string) => t.includes('ingestion_warnings'))
        expect(warningTopics).toHaveLength(1)
    })
})
