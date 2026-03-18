/**
 * # Chapter 1: Pipeline Fundamentals and Builders
 *
 * A pipeline is a linear sequence of processing steps that transform data.
 * Each step receives input from the previous step, performs some work, and
 * produces output for the next step.
 *
 * Pipelines are created using the builder pattern - this is the idiomatic
 * and recommended way to compose pipelines in this framework.
 *
 * ## Key Concepts
 *
 * - **Single-item pipelines** process one item at a time using `newPipelineBuilder()`
 * - **Batch pipelines** process multiple items efficiently using `newBatchPipelineBuilder()`
 * - **Steps** are functions that return a `Promise<PipelineResult<T>>`
 * - **Results** can be OK (success), DLQ (error), DROP (discard), or REDIRECT (route elsewhere)
 *
 * ## Step Definition Pattern
 *
 * Steps follow a factory pattern:
 * ```typescript
 * function createMyStep(): ProcessingStep<Input, Output> {
 *     return function myStep(input) {
 *         return Promise.resolve(ok(transformedValue))
 *     }
 * }
 * ```
 */
import { newBatchPipelineBuilder, newPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { PipelineResult, dlq, drop, isOkResult, ok, redirect } from '../results'
import { ProcessingStep } from '../steps'

/**
 * Type for batch processing steps - takes an array of values and returns
 * an array of results (must have same length).
 */
type BatchProcessingStep<T, U> = (values: T[]) => Promise<PipelineResult<U>[]>

describe('Defining Steps', () => {
    /**
     * Steps are defined using the factory pattern: a function that returns
     * the actual step function. This pattern enables:
     *
     * 1. **Dependency injection** - Pass config, clients, or other dependencies
     *    to the factory, which captures them in a closure
     * 2. **Named functions** - The inner function has a name that appears in
     *    stack traces and the `lastStep` context field
     * 3. **Type safety** - The factory return type `ProcessingStep<In, Out>`
     *    ensures the step signature is correct
     */
    it('steps use the factory pattern for dependency injection and naming', async () => {
        // A simple step with no dependencies
        function createUppercaseStep(): ProcessingStep<string, string> {
            return function uppercaseStep(input) {
                return Promise.resolve(ok(input.toUpperCase()))
            }
        }

        // A step that captures configuration via closure
        interface MultiplierConfig {
            factor: number
        }

        function createMultiplyStep(config: MultiplierConfig): ProcessingStep<number, number> {
            return function multiplyStep(input) {
                return Promise.resolve(ok(input * config.factor))
            }
        }

        // Use steps in pipelines
        const stringPipeline = newPipelineBuilder<string>().pipe(createUppercaseStep()).build()

        const numberPipeline = newPipelineBuilder<number>()
            .pipe(createMultiplyStep({ factor: 3 }))
            .build()

        const stringResult = await stringPipeline.process(createContext(ok('hello')))
        expect(isOkResult(stringResult.result) && stringResult.result.value).toBe('HELLO')

        const numberResult = await numberPipeline.process(createContext(ok(5)))
        expect(isOkResult(numberResult.result) && numberResult.result.value).toBe(15)
    })

    /**
     * Steps can add properties to their output, and subsequent steps receive
     * all accumulated properties. This enables progressive enrichment where
     * each step adds its own data to the result.
     *
     * Each step defines only the input properties it needs using `T extends Input`.
     * This allows the step to work with any object that has those properties,
     * passing through all other properties unchanged. This pattern allows
     * composition of steps without unnecessary coupling - steps don't need to
     * know about properties they don't use.
     */
    it('steps accumulate data through the pipeline', async () => {
        // Each step defines only the properties it NEEDS to read (Input)
        // and the properties it ADDS (Output extends Input with new properties)
        interface ValidateStepInput {
            eventId: string
        }

        interface ValidateStepOutput {
            isValid: boolean
        }

        interface EnrichStepInput {
            isValid: boolean
        }

        interface EnrichStepOutput {
            timestamp: number
        }

        interface FinalizeStepInput {
            eventId: string
            isValid: boolean
            timestamp: number
        }

        // Note: FinalizeStepOutput does NOT extend the input - this step produces
        // a summary and drops the intermediate properties. Steps can transform
        // data into completely different shapes.
        interface FinalizeStepOutput {
            summary: string
        }

        // Step uses T extends Input so it accepts any object with required properties
        // and passes through all other properties via spread
        function createValidateStep<T extends ValidateStepInput>(): ProcessingStep<T, T & ValidateStepOutput> {
            return function validateStep(input) {
                return Promise.resolve(ok({ ...input, isValid: true }))
            }
        }

        function createEnrichStep<T extends EnrichStepInput>(): ProcessingStep<T, T & EnrichStepOutput> {
            return function enrichStep(input) {
                return Promise.resolve(ok({ ...input, timestamp: Date.now() }))
            }
        }

        // This step does NOT use T extends - it reads all accumulated properties
        // and produces a new output shape, demonstrating that steps can also
        // drop properties and transform data completely.
        function createFinalizeStep(): ProcessingStep<FinalizeStepInput, FinalizeStepOutput> {
            return function finalizeStep(input) {
                // This step has access to ALL accumulated properties from previous steps
                // and produces a summary, dropping the intermediate properties
                return Promise.resolve(
                    ok({
                        summary: `Event ${input.eventId} valid=${input.isValid} at ${input.timestamp}`,
                    })
                )
            }
        }

        const pipeline = newPipelineBuilder<{ eventId: string }>()
            .pipe(createValidateStep())
            .pipe(createEnrichStep())
            .pipe(createFinalizeStep())
            .build()

        const result = await pipeline.process(createContext(ok({ eventId: 'evt-123' })))

        expect(isOkResult(result.result)).toBe(true)
        if (isOkResult(result.result)) {
            // Final result has ONLY the summary - previous properties were dropped
            expect(result.result.value.summary).toContain('evt-123')
            expect(result.result.value.summary).toContain('valid=true')
        }
    })
})

describe('Pipeline Fundamentals', () => {
    /**
     * A step can return OK to indicate successful processing and pass data
     * forward to the next step.
     */
    it('a step can return OK to pass data forward', async () => {
        interface ProcessDataResult {
            processed: string
        }

        function createProcessDataStep(): ProcessingStep<string, ProcessDataResult> {
            return function processDataStep(input) {
                return Promise.resolve(ok({ processed: input.toUpperCase() }))
            }
        }

        const pipeline = newPipelineBuilder<string>().pipe(createProcessDataStep()).build()

        const result = await pipeline.process(createContext(ok('hello')))

        expect(isOkResult(result.result)).toBe(true)
        if (isOkResult(result.result)) {
            expect(result.result.value).toEqual({ processed: 'HELLO' })
        }
    })

    /**
     * A pipeline transforms input through a sequence of steps.
     * Each step receives the output of the previous step and returns
     * a Promise<PipelineResult>.
     */
    it('a pipeline transforms input through a sequence of steps', async () => {
        function createUppercaseStep(): ProcessingStep<string, string> {
            return function uppercaseStep(input) {
                return Promise.resolve(ok(input.toUpperCase()))
            }
        }

        function createAddExclamationStep(): ProcessingStep<string, string> {
            return function addExclamationStep(input) {
                return Promise.resolve(ok(input + '!'))
            }
        }

        const pipeline = newPipelineBuilder<string>()
            .pipe(createUppercaseStep())
            .pipe(createAddExclamationStep())
            .build()

        const result = await pipeline.process(createContext(ok('hello')))

        expect(isOkResult(result.result)).toBe(true)
        if (isOkResult(result.result)) {
            expect(result.result.value).toBe('HELLO!')
        }
    })

    /**
     * A step can return DLQ (Dead Letter Queue) to signal an error that should
     * be handled by error handling infrastructure.
     */
    it('a step can return DLQ to signal an error', async () => {
        interface ValidateDataInput {
            value: number
        }

        function createValidateDataStep(): ProcessingStep<ValidateDataInput, ValidateDataInput> {
            return function validateDataStep(input) {
                if (input.value < 0) {
                    return Promise.resolve(dlq('Invalid value: must be non-negative', new Error('Validation failed')))
                }
                return Promise.resolve(ok(input))
            }
        }

        const pipeline = newPipelineBuilder<ValidateDataInput>().pipe(createValidateDataStep()).build()

        const result = await pipeline.process(createContext(ok({ value: -1 })))

        expect(result.result.type).toBe(1) // PipelineResultType.DLQ
    })

    /**
     * A step can return DROP to silently discard an item. This is useful for
     * filtering out items that should not be processed further but are not errors.
     */
    it('a step can return DROP to silently discard an item', async () => {
        interface Event {
            type: string
        }

        function createFilterInternalStep(): ProcessingStep<Event, Event> {
            return function filterInternalStep(event) {
                if (event.type === 'internal') {
                    return Promise.resolve(drop('Internal events are not processed'))
                }
                return Promise.resolve(ok(event))
            }
        }

        const pipeline = newPipelineBuilder<Event>().pipe(createFilterInternalStep()).build()

        const result = await pipeline.process(createContext(ok({ type: 'internal' })))

        expect(result.result.type).toBe(2) // PipelineResultType.DROP
    })

    /**
     * A step can return REDIRECT to send an item to a different destination
     * (e.g., a different Kafka topic) instead of continuing through the pipeline.
     */
    it('a step can return REDIRECT to send an item elsewhere', async () => {
        interface PriorityEvent {
            priority: string
        }

        function createRouteByPriorityStep(): ProcessingStep<PriorityEvent, PriorityEvent> {
            return function routeByPriorityStep(event) {
                if (event.priority === 'high') {
                    return Promise.resolve(redirect('High priority event', 'high-priority-topic'))
                }
                return Promise.resolve(ok(event))
            }
        }

        const pipeline = newPipelineBuilder<PriorityEvent>().pipe(createRouteByPriorityStep()).build()

        const result = await pipeline.process(createContext(ok({ priority: 'high' })))

        expect(result.result.type).toBe(3) // PipelineResultType.REDIRECT
    })

    /**
     * Non-OK results (DLQ, DROP, REDIRECT) short-circuit the pipeline - they
     * skip all remaining steps. OK results continue to propagate through
     * subsequent steps.
     */
    it('non-OK results short-circuit the pipeline, OK results propagate', async () => {
        type Input = { action: 'ok' | 'dlq' | 'drop' | 'redirect' }
        type Output = { action: string; processed: true }

        function createDecisionStep(): ProcessingStep<Input, Input> {
            return function decisionStep(input) {
                if (input.action === 'dlq') {
                    return Promise.resolve(dlq('Error condition'))
                }
                if (input.action === 'drop') {
                    return Promise.resolve(drop('Filtered out'))
                }
                if (input.action === 'redirect') {
                    return Promise.resolve(redirect('Redirecting', 'other-topic'))
                }
                return Promise.resolve(ok(input))
            }
        }

        function createProcessStep(): ProcessingStep<Input, Output> {
            return function processStep(input) {
                // This step expects only 'ok' actions - if short-circuiting failed,
                // we'd receive dlq/drop/redirect actions and this would be wrong
                if (input.action !== 'ok') {
                    throw new Error(`Unexpected action: ${input.action}`)
                }
                return Promise.resolve(ok({ action: input.action, processed: true }))
            }
        }

        const pipeline = newPipelineBuilder<Input>().pipe(createDecisionStep()).pipe(createProcessStep()).build()

        // OK result propagates through all steps
        const okResult = await pipeline.process(createContext(ok({ action: 'ok' })))
        expect(isOkResult(okResult.result)).toBe(true)
        expect(okResult.context.lastStep).toBe('processStep')

        // DLQ short-circuits - processStep is skipped
        const dlqResult = await pipeline.process(createContext(ok({ action: 'dlq' })))
        expect(dlqResult.result.type).toBe(1) // DLQ
        expect(dlqResult.context.lastStep).toBe('decisionStep')

        // DROP short-circuits - processStep is skipped
        const dropResult = await pipeline.process(createContext(ok({ action: 'drop' })))
        expect(dropResult.result.type).toBe(2) // DROP
        expect(dropResult.context.lastStep).toBe('decisionStep')

        // REDIRECT short-circuits - processStep is skipped
        const redirectResult = await pipeline.process(createContext(ok({ action: 'redirect' })))
        expect(redirectResult.result.type).toBe(3) // REDIRECT
        expect(redirectResult.context.lastStep).toBe('decisionStep')
    })
})

describe('Batch Pipelines', () => {
    /**
     * Batch pipelines are created using `newBatchPipelineBuilder()`. The builder
     * provides methods for adding batch steps, concurrent processing, and more.
     */
    it('batch pipelines are created using newBatchPipelineBuilder()', async () => {
        function createUppercaseBatchStep(): BatchProcessingStep<string, string> {
            return function uppercaseBatchStep(items) {
                return Promise.resolve(items.map((s) => ok(s.toUpperCase())))
            }
        }

        const pipeline = newBatchPipelineBuilder<string>().pipeBatch(createUppercaseBatchStep()).build()

        const batch = ['a', 'b', 'c'].map((s) => createContext(ok(s)))
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results).not.toBeNull()
        expect(results!.map((r) => (isOkResult(r.result) ? r.result.value : null))).toEqual(['A', 'B', 'C'])
    })

    /**
     * The `pipeBatch` method adds a step that processes the entire batch at once.
     * The step receives an array of values and must return an array of results
     * with the same length.
     */
    it('pipeBatch processes all items in a single call', async () => {
        const callCounts: number[] = []

        function createBatchEnrichStep(): BatchProcessingStep<number, number> {
            return function batchEnrichStep(items) {
                callCounts.push(items.length)
                return Promise.resolve(items.map((n) => ok(n * 10)))
            }
        }

        const pipeline = newBatchPipelineBuilder<number>().pipeBatch(createBatchEnrichStep()).build()

        const batch = [1, 2, 3, 4, 5].map((n) => createContext(ok(n)))
        pipeline.feed(batch)

        await pipeline.next()

        // Step was called once with all 5 items
        expect(callCounts).toEqual([5])
    })

    /**
     * Batch pipelines use a feed/next interface. Call `feed()` to add items
     * to the pipeline, then call `next()` to get processed results. `next()`
     * returns null when all items have been processed.
     */
    it('feed() accepts a batch of items and next() returns processed batches', async () => {
        function createPassthroughStep(): BatchProcessingStep<string, string> {
            return function passthroughStep(items) {
                return Promise.resolve(items.map((s) => ok(s)))
            }
        }

        const pipeline = newBatchPipelineBuilder<string>().pipeBatch(createPassthroughStep()).build()

        const batch = ['x', 'y'].map((s) => createContext(ok(s)))
        pipeline.feed(batch)

        const results1 = await pipeline.next()
        expect(results1).not.toBeNull()
        expect(results1!.length).toBe(2)

        const results2 = await pipeline.next()
        expect(results2).toBeNull() // No more items
    })
})
