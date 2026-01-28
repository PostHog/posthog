/**
 * # Chapter 13: Pipeline Conventions
 *
 * This chapter documents the conventions and patterns used when writing
 * pipeline steps and composing pipelines in the ingestion codebase.
 *
 * ## Overview
 *
 * - **Factory functions**: Steps are created via factory functions for DI and naming
 * - **Type extension**: Steps progressively enrich data using `T & NewProps`
 * - **Configuration injection**: Factory functions accept config parameters
 * - **Void returns**: Terminal steps return `void` to signal end of processing
 * - **Pipeline phases**: Preprocessing (pre/post team) vs processing separation
 * - **Subpipelines**: Large pipelines broken into composable pieces
 *
 * ## Type Definition Conventions
 *
 * **Best practice**: Define input, output, and config types separately from
 * function definitions. This improves readability and allows types to be
 * reused across multiple steps.
 *
 * **Never use `any`**: The framework is designed to leverage TypeScript's type
 * checker while minimizing boilerplate. If you find yourself needing `any`, it
 * indicates a structural problem with the code. Use `unknown` when the type is
 * genuinely unknown. This applies to tests as well - using `any` in tests can
 * mask actual issues with the code being tested.
 *
 * **Omit redundant type annotations**: Types for inner function arguments and
 * return types should be omitted - TypeScript infers these from the outer
 * function's return type annotation. This reduces noise and keeps code readable.
 */
import { Message } from 'node-rdkafka'

import { createTestMessage } from '../../../../tests/helpers/kafka-message'
import { createTestTeam } from '../../../../tests/helpers/team'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { Team } from '../../../types'
import { parseJSON } from '../../../utils/json-parse'
import { PromiseScheduler } from '../../../utils/promise-scheduler'
import { newBatchPipelineBuilder, newPipelineBuilder } from '../builders'
import { PipelineBuilder, StartPipelineBuilder } from '../builders/pipeline-builders'
import { createContext } from '../helpers'
import { PipelineConfig } from '../result-handling-pipeline'
import { dlq, isOkResult, ok } from '../results'
import { ProcessingStep } from '../steps'

describe('Factory Functions', () => {
    /**
     * Steps are created via factory functions that return the actual step.
     * This pattern enables:
     * - Dependency injection (pass services, config)
     * - Named functions for better stack traces
     * - Closure over dependencies
     */
    it('steps are created via factory functions', async () => {
        interface Input {
            value: string
        }

        interface Output {
            value: string
            processed: boolean
        }

        // Factory function returns a named step function
        function createProcessStep(): ProcessingStep<Input, Output> {
            return function processStep(input) {
                return Promise.resolve(ok({ value: input.value.toUpperCase(), processed: true }))
            }
        }

        const pipeline = newPipelineBuilder<Input>().pipe(createProcessStep()).build()

        const result = await pipeline.process(createContext(ok({ value: 'hello' })))

        expect(isOkResult(result.result) && result.result.value).toEqual({
            value: 'HELLO',
            processed: true,
        })
    })

    /**
     * Whole pipelines are also created via factory functions. This is essential
     * because batch pipelines are stateful (they maintain internal buffers via
     * feed/next) and should only have one caller. Creating pipelines via factory
     * functions ensures each consumer gets its own instance.
     */
    it('pipelines are created via factory functions to ensure single caller', async () => {
        interface Input {
            id: number
        }

        interface Output {
            id: number
            processed: boolean
        }

        function createProcessStep(): ProcessingStep<Input, Output> {
            return function processStep(input) {
                return Promise.resolve(ok({ id: input.id, processed: true }))
            }
        }

        // Factory function creates a new pipeline instance each time
        function createMyPipeline() {
            return newPipelineBuilder<Input>().pipe(createProcessStep()).build()
        }

        // Each caller gets their own pipeline instance
        const pipeline1 = createMyPipeline()
        const pipeline2 = createMyPipeline()

        // They are separate instances
        expect(pipeline1).not.toBe(pipeline2)

        // Each can be used independently
        const result1 = await pipeline1.process(createContext(ok({ id: 1 })))
        const result2 = await pipeline2.process(createContext(ok({ id: 2 })))

        expect(isOkResult(result1.result) && result1.result.value.id).toBe(1)
        expect(isOkResult(result2.result) && result2.result.value.id).toBe(2)
    })
})

describe('Configuration Injection', () => {
    /**
     * Factory functions accept configuration parameters for dependency injection.
     * This allows steps to be configured at pipeline construction time.
     */
    it('factory functions accept configuration parameters', async () => {
        interface Input {
            value: number
        }

        interface Output {
            value: number
            multiplied: number
        }

        interface MultiplyStepConfig {
            multiplier: number
        }

        // Factory accepts config and closes over it
        function createMultiplyStep(config: MultiplyStepConfig): ProcessingStep<Input, Output> {
            return function multiplyStep(input) {
                return Promise.resolve(
                    ok({
                        value: input.value,
                        multiplied: input.value * config.multiplier,
                    })
                )
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .pipe(createMultiplyStep({ multiplier: 3 }))
            .build()

        const result = await pipeline.process(createContext(ok({ value: 10 })))

        expect(isOkResult(result.result) && result.result.value.multiplied).toBe(30)
    })

    /**
     * Complex steps may need multiple dependencies injected.
     */
    it('factory functions can inject multiple dependencies', async () => {
        interface Input {
            userId: string
        }

        interface Output {
            userId: string
            userData: { name: string }
            auditLogged: boolean
        }

        // Mock services
        const mockUserService = {
            getUser: (id: string) => Promise.resolve({ name: `User ${id}` }),
        }
        const mockAuditService = {
            log: (_msg: string) => Promise.resolve(),
        }

        interface EnrichStepDependencies {
            userService: typeof mockUserService
            auditService: typeof mockAuditService
        }

        function createEnrichStep(deps: EnrichStepDependencies): ProcessingStep<Input, Output> {
            return async function enrichStep(input) {
                const userData = await deps.userService.getUser(input.userId)
                const auditPromise = deps.auditService.log(`Enriched user ${input.userId}`)
                return ok({ userId: input.userId, userData, auditLogged: true }, [auditPromise])
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .pipe(createEnrichStep({ userService: mockUserService, auditService: mockAuditService }))
            .build()

        const result = await pipeline.process(createContext(ok({ userId: '123' })))

        expect(isOkResult(result.result) && result.result.value.userData.name).toBe('User 123')
    })
})

describe('Type Extension', () => {
    /**
     * Steps use generic constraints to declare required input properties,
     * then extend the input type with new properties using `T & NewProps`.
     * This allows data to accumulate through the pipeline.
     */
    it('steps extend input types with new properties', async () => {
        // Step 1 only needs 'raw' property
        interface ValidateInput {
            raw: string
        }
        interface ValidateOutput {
            isValid: boolean
        }

        // Step 2 needs 'raw' and 'isValid'
        interface EnrichInput {
            raw: string
            isValid: boolean
        }
        interface EnrichOutput {
            enrichedAt: number
        }

        // Generic constraint: T must have ValidateInput properties
        // Output: T plus ValidateOutput (preserves all input properties)
        function createValidateStep<T extends ValidateInput>(): ProcessingStep<T, T & ValidateOutput> {
            return function validateStep(input) {
                return Promise.resolve(ok({ ...input, isValid: input.raw.length > 0 }))
            }
        }

        function createEnrichStep<T extends EnrichInput>(): ProcessingStep<T, T & EnrichOutput> {
            return function enrichStep(input) {
                return Promise.resolve(ok({ ...input, enrichedAt: Date.now() }))
            }
        }

        const pipeline = newPipelineBuilder<{ raw: string }>()
            .pipe(createValidateStep())
            .pipe(createEnrichStep())
            .build()

        const result = await pipeline.process(createContext(ok({ raw: 'test data' })))

        // Final result has all accumulated properties
        expect(isOkResult(result.result)).toBe(true)
        if (isOkResult(result.result)) {
            expect(result.result.value.raw).toBe('test data')
            expect(result.result.value.isValid).toBe(true)
            expect(result.result.value.enrichedAt).toBeGreaterThan(0)
        }
    })

    /**
     * Some steps transform input into a completely different shape.
     * These steps don't use generic extension - they define explicit input/output types.
     */
    it('terminal transforms produce different output shapes', async () => {
        interface ProcessedEvent {
            eventId: string
            isValid: boolean
            timestamp: number
        }

        interface EventSummary {
            summary: string
        }

        // No generic - produces completely different shape
        function createSummarizeStep(): ProcessingStep<ProcessedEvent, EventSummary> {
            return function summarizeStep(input) {
                return Promise.resolve(
                    ok({
                        summary: `Event ${input.eventId}: valid=${input.isValid} at ${input.timestamp}`,
                    })
                )
            }
        }

        const pipeline = newPipelineBuilder<ProcessedEvent>().pipe(createSummarizeStep()).build()

        const result = await pipeline.process(createContext(ok({ eventId: 'evt-1', isValid: true, timestamp: 1000 })))

        expect(isOkResult(result.result) && result.result.value.summary).toBe('Event evt-1: valid=true at 1000')
    })
})

describe('Void Returns', () => {
    /**
     * Terminal steps that don't pass data forward return `void`.
     * They use `ok(undefined, [...sideEffects])` to signal completion
     * while still attaching side effects.
     */
    it('terminal steps return void with side effects', async () => {
        const emittedEvents: string[] = []

        interface EventToEmit {
            eventId: string
            data: string
        }

        // Terminal step - returns void, no further processing
        function createEmitStep(): ProcessingStep<EventToEmit, void> {
            return function emitStep(input) {
                const emitPromise = Promise.resolve().then(() => {
                    emittedEvents.push(input.eventId)
                })
                // Return ok(undefined) with side effect
                return Promise.resolve(ok(undefined, [emitPromise]))
            }
        }

        const pipeline = newPipelineBuilder<EventToEmit>().pipe(createEmitStep()).build()

        const result = await pipeline.process(createContext(ok({ eventId: 'evt-1', data: 'test' })))

        // Result is OK with undefined value
        expect(isOkResult(result.result)).toBe(true)
        if (isOkResult(result.result)) {
            expect(result.result.value).toBeUndefined()
        }

        // Side effect was captured
        await Promise.all(result.context.sideEffects)
        expect(emittedEvents).toContain('evt-1')
    })

    /**
     * Simple terminal steps may not need side effects at all.
     */
    it('simple terminal steps return ok(undefined)', async () => {
        interface Input {
            shouldSkip: boolean
        }

        // Skip step - just ends processing without doing anything
        function createSkipStep(): ProcessingStep<Input, void> {
            return function skipStep(_input) {
                return Promise.resolve(ok(undefined))
            }
        }

        const pipeline = newPipelineBuilder<Input>().pipe(createSkipStep()).build()

        const result = await pipeline.process(createContext(ok({ shouldSkip: true })))

        expect(isOkResult(result.result)).toBe(true)
    })
})

describe('Pipeline Phases', () => {
    /**
     * Large pipelines are organized into phases, each as a separate subpipeline:
     * 1. Pre-team preprocessing: parsing, validation before team lookup
     * 2. Post-team preprocessing: team-specific validation, enrichment
     * 3. Processing: core business logic, event creation, emission
     *
     * This separation allows:
     * - Early rejection of invalid events (before expensive team lookup)
     * - Team-specific logic isolated from parsing
     * - Clear boundaries for testing and maintenance
     * - Independent testing of each phase
     */
    it('pipelines are organized into preprocessing and processing phases', async () => {
        const phaseLog: string[] = []
        const promiseScheduler = new PromiseScheduler()
        const mockKafkaProducer = {
            producer: {},
            queueMessages: jest.fn().mockResolvedValue(undefined),
        } as unknown as KafkaProducerWrapper

        interface RawInput {
            message: Message
        }

        interface PreTeamOutput {
            teamId: number
            eventName: string
            team: Team
        }

        interface PostTeamOutput {
            validated: boolean
        }

        interface ProcessingOutput {
            result: string
        }

        // Steps for each phase (single-item steps used inside sequentially)
        function createParseStep<T extends RawInput>(): ProcessingStep<T, T & PreTeamOutput> {
            return function parseStep(item) {
                phaseLog.push('pre-team: parse')
                try {
                    const parsed = parseJSON(item.message.value?.toString() ?? '{}')
                    const team = createTestTeam({ id: parsed.teamId })
                    return Promise.resolve(ok({ ...item, teamId: parsed.teamId, eventName: parsed.eventName, team }))
                } catch (e) {
                    return Promise.resolve(dlq('Failed to parse message', e as Error))
                }
            }
        }

        function createValidateStep<T extends PreTeamOutput>(): ProcessingStep<T, T & PostTeamOutput> {
            return function validateStep(item) {
                phaseLog.push('post-team: validate')
                return Promise.resolve(ok({ ...item, validated: true }))
            }
        }

        function createProcessStep<T extends PreTeamOutput & PostTeamOutput>(): ProcessingStep<
            T,
            T & ProcessingOutput
        > {
            return function processStep(item) {
                phaseLog.push('processing: process')
                return Promise.resolve(ok({ ...item, result: `${item.eventName} for Team ${item.teamId}` }))
            }
        }

        // Subpipelines take a StartPipelineBuilder and return a PipelineBuilder
        function createPreTeamPreprocessingSubpipeline<T extends RawInput, C>(
            builder: StartPipelineBuilder<T, C>
        ): PipelineBuilder<T, T & PreTeamOutput, C> {
            return builder.pipe(createParseStep<T>())
        }

        function createPostTeamPreprocessingSubpipeline<T extends PreTeamOutput, C>(
            builder: StartPipelineBuilder<T, C>
        ): PipelineBuilder<T, T & PostTeamOutput, C> {
            return builder.pipe(createValidateStep<T>())
        }

        function createProcessingSubpipeline<T extends PreTeamOutput & PostTeamOutput, C>(
            builder: StartPipelineBuilder<T, C>
        ): PipelineBuilder<T, T & ProcessingOutput, C> {
            return builder.pipe(createProcessStep<T>())
        }

        const pipelineConfig: PipelineConfig = {
            kafkaProducer: mockKafkaProducer,
            dlqTopic: 'test-dlq',
            promiseScheduler,
        }

        // Compose subpipelines like joined-ingestion-pipeline
        function createPipeline() {
            return (
                newBatchPipelineBuilder<RawInput, { message: Message }>()
                    // Pre-team preprocessing: parse and resolve team (concurrent)
                    .messageAware((b) => b.concurrently((b) => createPreTeamPreprocessingSubpipeline(b)))
                    .handleResults(pipelineConfig)
                    .handleSideEffects(promiseScheduler, { await: false })
                    .gather()
                    .filterOk()
                    // Add team to context
                    .map((element) => ({
                        result: element.result,
                        context: { ...element.context, team: element.result.value.team },
                    }))
                    .messageAware((b) =>
                        b
                            .teamAware((b) =>
                                b
                                    // Post-team preprocessing: validate (concurrent)
                                    .concurrently((b) => createPostTeamPreprocessingSubpipeline(b))
                                    // Processing: group by team and process sequentially within each group
                                    .groupBy((item) => item.teamId)
                                    .concurrently((group) => group.sequentially((b) => createProcessingSubpipeline(b)))
                                    .gather()
                            )
                            .handleIngestionWarnings(mockKafkaProducer)
                    )
                    .handleResults(pipelineConfig)
                    .handleSideEffects(promiseScheduler, { await: true })
                    .gather()
                    .build()
            )
        }

        const pipeline = createPipeline()
        const message = createTestMessage({ value: Buffer.from(JSON.stringify({ teamId: 42, eventName: 'pageview' })) })
        const batch = [createContext(ok<RawInput>({ message }), { message })]
        pipeline.feed(batch)
        const results = await pipeline.next()

        expect(phaseLog).toEqual(['pre-team: parse', 'post-team: validate', 'processing: process'])
        expect(results).toHaveLength(1)
        if (isOkResult(results![0].result)) {
            expect(results![0].result.value.result).toBe('pageview for Team 42')
        }
    })
})
