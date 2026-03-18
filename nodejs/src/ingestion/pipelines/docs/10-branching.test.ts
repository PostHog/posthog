/**
 * # Chapter 10: Branching
 *
 * The `branching()` method routes items to different sub-pipelines based on
 * a decision function. This is useful when different types of items need
 * different processing logic.
 *
 * ## How Branching Works
 *
 * 1. A decision function determines which branch each item goes to
 * 2. Each item is routed to exactly one branch
 * 3. Each branch can have its own processing logic
 * 4. All branches must converge to the same output type
 *
 * ## Use Cases
 *
 * - Event type routing: Different processing for pageviews vs clicks
 * - Priority handling: High-priority items get special processing
 * - Feature flags: Route to different implementations
 */
import { newPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { isDlqResult, isOkResult, ok } from '../results'
import { ProcessingStep } from '../steps'

type Event = {
    type: 'pageview' | 'click' | 'custom'
    data: string
}

type ProcessedEvent = {
    type: string
    data: string
    processedBy: string
}

describe('Branching', () => {
    /**
     * The `branching()` method routes items based on a decision function.
     * Each branch can have its own processing logic, and items go to
     * exactly one branch based on the decision function's return value.
     */
    it('branching() routes items to different sub-pipelines', async () => {
        const branchCalls: string[] = []

        function createPageviewStep(): ProcessingStep<Event, ProcessedEvent> {
            return function pageviewStep(event) {
                branchCalls.push('pageview')
                return Promise.resolve(ok({ type: event.type, data: `PAGE: ${event.data}`, processedBy: 'pageview' }))
            }
        }

        function createClickStep(): ProcessingStep<Event, ProcessedEvent> {
            return function clickStep(event) {
                branchCalls.push('click')
                return Promise.resolve(ok({ type: event.type, data: `CLICK: ${event.data}`, processedBy: 'click' }))
            }
        }

        function createCustomStep(): ProcessingStep<Event, ProcessedEvent> {
            return function customStep(event) {
                branchCalls.push('custom')
                return Promise.resolve(ok({ type: event.type, data: event.data, processedBy: 'custom' }))
            }
        }

        const pipeline = newPipelineBuilder<Event>()
            .branching<Event['type'], ProcessedEvent>(
                (event) => event.type,
                (builder) => {
                    builder
                        .branch('pageview', (b) => b.pipe(createPageviewStep()))
                        .branch('click', (b) => b.pipe(createClickStep()))
                        .branch('custom', (b) => b.pipe(createCustomStep()))
                }
            )
            .build()

        // Process items through different branches
        const pageviewResult = await pipeline.process(createContext(ok<Event>({ type: 'pageview', data: 'home' })))
        const clickResult = await pipeline.process(createContext(ok<Event>({ type: 'click', data: 'button' })))

        // Each branch applies its own processing logic
        expect(isOkResult(pageviewResult.result) && pageviewResult.result.value.data).toBe('PAGE: home')
        expect(isOkResult(clickResult.result) && clickResult.result.value.data).toBe('CLICK: button')

        // Each item goes to exactly one branch
        expect(branchCalls).toEqual(['pageview', 'click'])
    })

    /**
     * If the decision function returns a branch name that isn't defined,
     * the item is sent to DLQ.
     */
    it('unknown branch routes to DLQ', async () => {
        type FlexibleEvent = { type: string; data: string }

        function createPageviewStep(): ProcessingStep<FlexibleEvent, ProcessedEvent> {
            return function pageviewStep(event) {
                return Promise.resolve(ok({ type: event.type, data: event.data, processedBy: 'pageview' }))
            }
        }

        const pipeline = newPipelineBuilder<FlexibleEvent>()
            .branching<string, ProcessedEvent>(
                (event) => event.type,
                (builder) => {
                    builder.branch('pageview', (b) => b.pipe(createPageviewStep()))
                }
            )
            .build()

        const result = await pipeline.process(createContext(ok<FlexibleEvent>({ type: 'unknown', data: 'test' })))

        expect(isDlqResult(result.result)).toBe(true)
    })

    /**
     * Branches can produce different intermediate types, but they must all
     * converge to a common output type (typically a union type).
     */
    it('branches must converge to the same output type', async () => {
        type NumberOutput = { kind: 'number'; value: number }
        type StringOutput = { kind: 'string'; value: string }
        type Output = NumberOutput | StringOutput
        type Input = { branch: 'toNumber' | 'toString'; input: string }

        function createToNumberStep(): ProcessingStep<Input, Output> {
            return function toNumberStep(input) {
                return Promise.resolve(ok({ kind: 'number' as const, value: parseInt(input.input, 10) }))
            }
        }

        function createToStringStep(): ProcessingStep<Input, Output> {
            return function toStringStep(input) {
                return Promise.resolve(ok({ kind: 'string' as const, value: input.input.toUpperCase() }))
            }
        }

        const pipeline = newPipelineBuilder<Input>()
            .branching<Input['branch'], Output>(
                (input) => input.branch,
                (builder) => {
                    builder
                        .branch('toNumber', (b) => b.pipe(createToNumberStep()))
                        .branch('toString', (b) => b.pipe(createToStringStep()))
                }
            )
            .build()

        const numberResult = await pipeline.process(createContext(ok<Input>({ branch: 'toNumber', input: '42' })))
        const stringResult = await pipeline.process(createContext(ok<Input>({ branch: 'toString', input: 'hello' })))

        expect(isOkResult(numberResult.result) && numberResult.result.value).toEqual({ kind: 'number', value: 42 })
        expect(isOkResult(stringResult.result) && stringResult.result.value).toEqual({ kind: 'string', value: 'HELLO' })
    })
})
