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
 * 4. Side effects send warnings to Kafka; category and severity are resolved
 *    from `INGESTION_WARNING_TYPES` at serialization time
 *
 * ## Warning Structure
 *
 * ```typescript
 * interface PipelineWarning {
 *     type: IngestionWarningType    // Must be registered in INGESTION_WARNING_TYPES
 *                                   // (ingestion/common/ingestion-warnings.ts)
 *     details: Record<string, any>  // Additional context
 *     key?: string              // Optional key for debouncing
 *     alwaysSend?: boolean      // Bypass debouncing for critical warnings
 * }
 * ```
 *
 * New warning types must be added to the registry first — the registry fixes the
 * type's category and severity so every emission is consistently classified.
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
import { IngestionWarningsOutput } from '~/common/outputs'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { newBatchPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { PipelineResult, isOkResult, ok } from '~/ingestion/framework/results'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { createTestTeam } from '~/tests/helpers/team'
import { Team } from '~/types'

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
                                type: 'schema_validation_failed',
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

        const batch = [createOkContext({ name: 'pageview' }, { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results).toHaveLength(1)
        expect(isOkResult(results![0].result)).toBe(true)
        expect(results![0].context.warnings).toHaveLength(1)
        expect(results![0].context.warnings[0]).toEqual({
            type: 'schema_validation_failed',
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
                                type: 'ignored_invalid_timestamp',
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
                                type: 'schema_validation_failed',
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

        const batch = [createOkContext({ name: 'click' }, { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        // Both warnings from both steps are accumulated
        expect(results![0].context.warnings).toHaveLength(2)
        expect(results![0].context.warnings.map((w) => w.type)).toEqual([
            'ignored_invalid_timestamp',
            'schema_validation_failed',
        ])
    })

    /**
     * A single step can add multiple warnings for different issues.
     */
    it('a step can add multiple warnings', async () => {
        interface Event {
            name: string
            timestamp?: string
            properties: Record<string, any>
        }

        function createComprehensiveValidationStep(): BatchProcessingStep<Event, Event> {
            return function comprehensiveValidationStep(items) {
                return Promise.resolve(
                    items.map((item) => {
                        const warnings: PipelineWarning[] = []

                        const groupKey = item.properties['$group_key']
                        if (groupKey && String(groupKey).length > 400) {
                            warnings.push({
                                type: 'group_key_too_long',
                                details: { groupKey: String(groupKey).slice(0, 20), max: 400 },
                            })
                        }

                        if (item.timestamp && isNaN(Date.parse(item.timestamp))) {
                            warnings.push({
                                type: 'ignored_invalid_timestamp',
                                details: { value: item.timestamp },
                            })
                        }

                        const processPerson = item.properties['$process_person_profile']
                        if (processPerson !== undefined && typeof processPerson !== 'boolean') {
                            warnings.push({
                                type: 'invalid_process_person_profile',
                                details: { received: typeof processPerson },
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
        const properties: Record<string, any> = {
            $group_key: 'g'.repeat(500),
            $process_person_profile: 'yes', // Not a boolean
        }

        const batch = [createOkContext({ name: '$groupidentify', timestamp: 'not-a-date', properties }, { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results![0].context.warnings).toHaveLength(3)
        expect(results![0].context.warnings.map((w) => w.type)).toContain('group_key_too_long')
        expect(results![0].context.warnings.map((w) => w.type)).toContain('ignored_invalid_timestamp')
        expect(results![0].context.warnings.map((w) => w.type)).toContain('invalid_process_person_profile')
    })
})

describe('Handling Ingestion Warnings', () => {
    /**
     * The `handleIngestionWarnings()` method converts warnings to side effects
     * that send them to Kafka. It requires team context via `teamAware()`.
     * Use `handleSideEffects()` to execute the warning side effects.
     */
    it('handleIngestionWarnings converts warnings to side effects', async () => {
        const mockOutputs = createMockIngestionOutputs<IngestionWarningsOutput>()
        const promiseScheduler = new PromiseScheduler()

        interface Event {
            name: string
        }

        function createWarningStep(): BatchProcessingStep<Event, Event> {
            return function warningStep(items) {
                return Promise.resolve(
                    items.map((item) =>
                        ok(item, [], [{ type: 'client_ingestion_warning', details: { eventName: item.name } }])
                    )
                )
            }
        }

        const team = createTestTeam({ id: 42 })
        const pipeline = newBatchPipelineBuilder<Event, { team: Team }>()
            .pipeBatch(createWarningStep())
            .teamAware((builder) => builder)
            .handleIngestionWarnings(mockOutputs)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const batch = [createOkContext({ name: 'pageview' }, { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        // Warnings are cleared after handling
        expect(results![0].context.warnings).toEqual([])

        // Side effects were executed (warning sent to Kafka via outputs)
        expect(mockOutputs.queueMessages).toHaveBeenCalled()
    })

    /**
     * Existing side effects are preserved when handling warnings.
     * Both the original side effects and warning side effects are executed.
     */
    it('handleIngestionWarnings preserves existing side effects', async () => {
        const mockOutputs = createMockIngestionOutputs<IngestionWarningsOutput>()
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
                        const warnings: PipelineWarning[] = [{ type: 'client_ingestion_warning', details: {} }]
                        return ok(item, [sideEffect], warnings)
                    })
                )
            }
        }

        const team = createTestTeam()
        const pipeline = newBatchPipelineBuilder<Event, { team: Team }>()
            .pipeBatch(createStepWithBothSideEffectsAndWarnings())
            .teamAware((builder) => builder)
            .handleIngestionWarnings(mockOutputs)
            .handleSideEffects(promiseScheduler, { await: true })
            .build()

        const batch = [createOkContext({ name: 'click' }, { team })]
        pipeline.feed(batch)

        await pipeline.next()

        // Original side effect executed
        expect(sideEffectLog).toContain('processed: click')

        // Warning side effect executed (sent to Kafka via outputs)
        expect(mockOutputs.queueMessages).toHaveBeenCalled()
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
                                    type: 'cannot_merge_already_identified',
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

        const batch = [createOkContext({ distinctId: 'user-123' }, { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results![0].context.warnings[0]).toEqual({
            type: 'cannot_merge_already_identified',
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
                                    type: 'message_size_too_large',
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

        const batch = [createOkContext({ name: 'important_event' }, { team })]
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results![0].context.warnings[0]).toEqual({
            type: 'message_size_too_large',
            details: { eventName: 'important_event' },
            key: 'quota',
            alwaysSend: true,
        })
    })
})
