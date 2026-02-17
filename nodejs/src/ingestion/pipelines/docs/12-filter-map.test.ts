/**
 * # Chapter 12: Filter Map Pattern
 *
 * The `filterMap()` method filters OK results, applies a mapping function to transform
 * values and context, and processes them through a subpipeline. Non-OK results pass
 * through unchanged.
 *
 * ## Common Use Case: Adding Team to Context
 *
 * Many pipeline operations are team-scoped (like `teamAware()` and
 * `handleIngestionWarnings()`). These methods require `team` to be present in the
 * pipeline context - if it's not, the code will not compile.
 *
 * When team data comes from a lookup step, `filterMap()` allows us to:
 * 1. Filter OK results (failed lookups pass through as non-OK)
 * 2. Extract team from the result and add to context
 * 3. Process through a team-aware subpipeline
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

describe('Filter Map', () => {
    /**
     * The `teamAware()` method requires `{ team: Team }` in the pipeline context.
     * Without it, TypeScript will report a compile error.
     *
     * `filterMap()` filters OK results, maps them (adding team to context), and
     * processes through a subpipeline. Non-OK results pass through unchanged.
     */
    it('filterMap enables team-aware processing with non-OK passthrough', async () => {
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

        // filterMap() filters OK results, maps them, and processes through subpipeline.
        // Non-OK results pass through unchanged, so we only need handleResults once at the end.
        const pipeline = newBatchPipelineBuilder<RawEvent, { message: Message }>()
            .pipeBatch(createTeamLookupStep())
            .gather()
            .filterMap(
                // Map: extract team from result and add to context
                (element) => ({
                    result: element.result,
                    context: {
                        ...element.context,
                        team: element.result.value.team,
                    },
                }),
                // Subpipeline: process events with team context
                (b) =>
                    b
                        .teamAware((b) => b.pipeBatch(createProcessEventStep()).gather())
                        .handleIngestionWarnings(mockKafkaProducer as any)
            )
            // Handle all results (both from subpipeline and passed-through non-OK) once at the end
            .messageAware((builder) => builder)
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const batch = [
            createContext(ok<RawEvent>({ teamId: 1, name: 'pageview' }), { message: createTestMessage() }),
            createContext(ok<RawEvent>({ teamId: 999, name: 'will_fail' }), { message: createTestMessage() }),
            createContext(ok<RawEvent>({ teamId: 2, name: 'overflow' }), { message: createTestMessage() }),
            createContext(ok<RawEvent>({ teamId: 3, name: 'deprecated_event' }), { message: createTestMessage() }),
        ]
        pipeline.feed(batch)

        // Drain all results (non-OK may come first due to streaming)
        const allResults: any[] = []
        let result = await pipeline.next()
        while (result !== null) {
            allResults.push(...result)
            result = await pipeline.next()
        }

        // 4 results total: DLQ passes through, redirect passes through, two OK
        expect(allResults).toHaveLength(4)

        // Two events are OK (pageview and deprecated_event)
        const okResults = allResults.filter((r) => isOkResult(r.result))
        expect(okResults).toHaveLength(2)

        // Verify the pageview and deprecated events were processed
        expect(processedEvents).toEqual([
            { eventName: 'pageview', teamId: 1 },
            { eventName: 'deprecated_event', teamId: 3 },
        ])

        // Verify Kafka producer was called for DLQ and redirect
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
