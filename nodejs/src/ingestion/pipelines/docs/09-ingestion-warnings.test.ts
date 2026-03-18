/**
 * # Chapter 9: Ingestion Warnings
 *
 * Ingestion warnings signal to customers that there were problems ingesting
 * their events, typically due to events being malformed or incorrect in some
 * manner. Unlike errors (which send items to DLQ), warnings allow processing
 * to continue while recording the issue for customer visibility.
 *
 * Warnings are displayed to customers in the PostHog UI.
 *
 * ## Use Cases
 *
 * - **Schema issues**: Missing required fields, unexpected types
 * - **Data quality**: Truncated values, deprecated formats
 * - **Limits**: Rate limiting, quota warnings
 * - **Deprecations**: Old API versions, deprecated event types
 *
 * ## How Warnings Work
 *
 * 1. Steps add warnings to results using the third parameter of `ok()`
 * 2. Warnings accumulate through the pipeline in context
 * 3. `handleIngestionWarnings()` converts warnings to side effects
 * 4. Side effects send warnings to Kafka for display in the UI
 *
 * ## Warning Structure
 *
 * ```typescript
 * interface PipelineWarning {
 *     type: string              // Warning category (e.g., 'missing_field')
 *     details: Record<string, any>  // Additional context
 *     key?: string              // Optional key for debouncing
 *     alwaysSend?: boolean      // Bypass debouncing for critical warnings
 * }
 * ```
 *
 * ## Team Context Requirement
 *
 * Warnings are team-scoped - they appear in a specific team's UI. Therefore,
 * `handleIngestionWarnings()` is only available through the `teamAware()`
 * builder method, which requires `{ team: Team }` in the context.
 *
 * **Important**: Warnings returned from steps outside of `teamAware()` will be
 * ignored and never sent to Kafka. Always ensure `handleIngestionWarnings()`
 * is called within a `teamAware()` block to process warnings.
 */
import { createTestTeam } from '../../../../tests/helpers/team'
import { Team } from '../../../types'
import { PromiseScheduler } from '../../../utils/promise-scheduler'
import { newBatchPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { PipelineWarning } from '../pipeline.interface'
import { PipelineResult, isOkResult, ok } from '../results'

type BatchProcessingStep<T, U> = (values: T[]) => Promise<PipelineResult<U>[]>

describe('Warning Basics', () => {
    /**
     * Steps can add warnings to results using the third parameter of `ok()`.
     * The first parameter is the value, second is side effects, third is warnings.
     */
    it('steps can add warnings to results', async () => {
        interface Event {
            name: string
            properties?: Record<string, any>
        }

        function createValidationStep(): BatchProcessingStep<Event, Event> {
            return function validationStep(items) {
                return Promise.resolve(
                    items.map((item) => {
                        const warnings: PipelineWarning[] = []

                        if (!item.properties) {
                            warnings.push({
                                type: 'missing_properties',
                                details: { eventName: item.name },
                            })
                        }

                        return ok(item, [], warnings)
                    })
                )
            }
        }

        const team = createTestTeam()
        const pipeline = newBatchPipelineBuilder<Event, { team: Team }>().pipeBatch(createValidationStep()).build()

        const batch = [createContext(ok({ name: 'pageview' }), { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results).toHaveLength(1)
        expect(isOkResult(results![0].result)).toBe(true)
        expect(results![0].context.warnings).toHaveLength(1)
        expect(results![0].context.warnings[0]).toEqual({
            type: 'missing_properties',
            details: { eventName: 'pageview' },
        })
    })

    /**
     * Warnings accumulate through the pipeline - each step can add warnings
     * and they're all collected in the context.
     */
    it('warnings accumulate through the pipeline', async () => {
        interface Event {
            name: string
            timestamp?: string
            properties?: Record<string, any>
        }

        function createTimestampCheckStep(): BatchProcessingStep<Event, Event> {
            return function timestampCheckStep(items) {
                return Promise.resolve(
                    items.map((item) => {
                        const warnings: PipelineWarning[] = []
                        if (!item.timestamp) {
                            warnings.push({
                                type: 'missing_timestamp',
                                details: { eventName: item.name },
                            })
                        }
                        return ok(item, [], warnings)
                    })
                )
            }
        }

        function createPropertiesCheckStep(): BatchProcessingStep<Event, Event> {
            return function propertiesCheckStep(items) {
                return Promise.resolve(
                    items.map((item) => {
                        const warnings: PipelineWarning[] = []
                        if (!item.properties) {
                            warnings.push({
                                type: 'missing_properties',
                                details: { eventName: item.name },
                            })
                        }
                        return ok(item, [], warnings)
                    })
                )
            }
        }

        const team = createTestTeam()
        const pipeline = newBatchPipelineBuilder<Event, { team: Team }>()
            .pipeBatch(createTimestampCheckStep())
            .pipeBatch(createPropertiesCheckStep())
            .build()

        const batch = [createContext(ok({ name: 'click' }), { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        // Both warnings from both steps are accumulated
        expect(results![0].context.warnings).toHaveLength(2)
        expect(results![0].context.warnings.map((w) => w.type)).toEqual(['missing_timestamp', 'missing_properties'])
    })

    /**
     * A single step can add multiple warnings for different issues.
     */
    it('a step can add multiple warnings', async () => {
        interface Event {
            name: string
            properties: Record<string, any>
        }

        function createComprehensiveValidationStep(): BatchProcessingStep<Event, Event> {
            return function comprehensiveValidationStep(items) {
                return Promise.resolve(
                    items.map((item) => {
                        const warnings: PipelineWarning[] = []

                        if (item.name.length > 50) {
                            warnings.push({
                                type: 'event_name_too_long',
                                details: { length: item.name.length, max: 50 },
                            })
                        }

                        if (Object.keys(item.properties).length > 100) {
                            warnings.push({
                                type: 'too_many_properties',
                                details: { count: Object.keys(item.properties).length, max: 100 },
                            })
                        }

                        if (item.properties['$ip'] && typeof item.properties['$ip'] !== 'string') {
                            warnings.push({
                                type: 'invalid_ip_type',
                                details: { received: typeof item.properties['$ip'] },
                            })
                        }

                        return ok(item, [], warnings)
                    })
                )
            }
        }

        const team = createTestTeam()
        const pipeline = newBatchPipelineBuilder<Event, { team: Team }>()
            .pipeBatch(createComprehensiveValidationStep())
            .build()

        // Create an event that triggers multiple warnings
        const longName = 'a'.repeat(60)
        const manyProperties: Record<string, any> = {}
        for (let i = 0; i < 110; i++) {
            manyProperties[`prop${i}`] = i
        }
        manyProperties['$ip'] = 12345 // Wrong type

        const batch = [createContext(ok({ name: longName, properties: manyProperties }), { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results![0].context.warnings).toHaveLength(3)
        expect(results![0].context.warnings.map((w) => w.type)).toContain('event_name_too_long')
        expect(results![0].context.warnings.map((w) => w.type)).toContain('too_many_properties')
        expect(results![0].context.warnings.map((w) => w.type)).toContain('invalid_ip_type')
    })
})

describe('Handling Ingestion Warnings', () => {
    /**
     * The `handleIngestionWarnings()` method converts warnings to side effects
     * that send them to Kafka. It requires team context via `teamAware()`.
     * Use `handleSideEffects()` to execute the warning side effects.
     */
    it('handleIngestionWarnings converts warnings to side effects', async () => {
        const mockKafkaProducer = {
            queueMessages: jest.fn().mockResolvedValue(undefined),
        }
        const promiseScheduler = new PromiseScheduler()

        interface Event {
            name: string
        }

        function createWarningStep(): BatchProcessingStep<Event, Event> {
            return function warningStep(items) {
                return Promise.resolve(
                    items.map((item) => ok(item, [], [{ type: 'test_warning', details: { eventName: item.name } }]))
                )
            }
        }

        const team = createTestTeam({ id: 42 })
        const pipeline = newBatchPipelineBuilder<Event, { team: Team }>()
            .pipeBatch(createWarningStep())
            .teamAware((builder) => builder)
            .handleIngestionWarnings(mockKafkaProducer as any)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const batch = [createContext(ok({ name: 'pageview' }), { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        // Warnings are cleared after handling
        expect(results![0].context.warnings).toEqual([])

        // Side effects were executed (warning sent to Kafka)
        expect(mockKafkaProducer.queueMessages).toHaveBeenCalled()
    })

    /**
     * Existing side effects are preserved when handling warnings.
     * Both the original side effects and warning side effects are executed.
     */
    it('handleIngestionWarnings preserves existing side effects', async () => {
        const mockKafkaProducer = {
            queueMessages: jest.fn().mockResolvedValue(undefined),
        }
        const promiseScheduler = new PromiseScheduler()

        const sideEffectLog: string[] = []

        interface Event {
            name: string
        }

        function createStepWithBothSideEffectsAndWarnings(): BatchProcessingStep<Event, Event> {
            return function stepWithBothSideEffectsAndWarnings(items) {
                return Promise.resolve(
                    items.map((item) => {
                        const sideEffect = Promise.resolve().then(() => sideEffectLog.push(`processed: ${item.name}`))
                        const warnings: PipelineWarning[] = [{ type: 'info', details: {} }]
                        return ok(item, [sideEffect], warnings)
                    })
                )
            }
        }

        const team = createTestTeam()
        const pipeline = newBatchPipelineBuilder<Event, { team: Team }>()
            .pipeBatch(createStepWithBothSideEffectsAndWarnings())
            .teamAware((builder) => builder)
            .handleIngestionWarnings(mockKafkaProducer as any)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const batch = [createContext(ok({ name: 'click' }), { team })]
        pipeline.feed(batch)

        await pipeline.next()

        // Original side effect executed
        expect(sideEffectLog).toContain('processed: click')

        // Warning side effect executed (sent to Kafka)
        expect(mockKafkaProducer.queueMessages).toHaveBeenCalled()
    })
})

describe('Warning Debouncing', () => {
    /**
     * Warnings with the same team + type + key are debounced to avoid
     * flooding the system with duplicate warnings.
     */
    it('warnings can include a key for debouncing', async () => {
        interface Event {
            distinctId: string
        }

        function createUserWarningStep(): BatchProcessingStep<Event, Event> {
            return function userWarningStep(items) {
                return Promise.resolve(
                    items.map((item) =>
                        ok(
                            item,
                            [],
                            [
                                {
                                    type: 'user_rate_limited',
                                    details: { distinctId: item.distinctId },
                                    key: item.distinctId, // Debounce by user
                                },
                            ]
                        )
                    )
                )
            }
        }

        const team = createTestTeam()
        const pipeline = newBatchPipelineBuilder<Event, { team: Team }>().pipeBatch(createUserWarningStep()).build()

        const batch = [createContext(ok({ distinctId: 'user-123' }), { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results![0].context.warnings[0]).toEqual({
            type: 'user_rate_limited',
            details: { distinctId: 'user-123' },
            key: 'user-123',
        })
    })

    /**
     * The `alwaysSend` flag bypasses debouncing for critical warnings
     * that must always be recorded.
     */
    it('alwaysSend bypasses debouncing for critical warnings', async () => {
        interface Event {
            name: string
        }

        function createCriticalWarningStep(): BatchProcessingStep<Event, Event> {
            return function criticalWarningStep(items) {
                return Promise.resolve(
                    items.map((item) =>
                        ok(
                            item,
                            [],
                            [
                                {
                                    type: 'quota_exceeded',
                                    details: { eventName: item.name },
                                    key: 'quota',
                                    alwaysSend: true, // Always send, never debounce
                                },
                            ]
                        )
                    )
                )
            }
        }

        const team = createTestTeam()
        const pipeline = newBatchPipelineBuilder<Event, { team: Team }>().pipeBatch(createCriticalWarningStep()).build()

        const batch = [createContext(ok({ name: 'important_event' }), { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results![0].context.warnings[0]).toEqual({
            type: 'quota_exceeded',
            details: { eventName: 'important_event' },
            key: 'quota',
            alwaysSend: true,
        })
    })
})
