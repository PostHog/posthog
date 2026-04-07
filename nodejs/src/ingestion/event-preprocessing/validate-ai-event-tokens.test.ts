import { createTestPipelineEvent } from '../../../tests/helpers/pipeline-event'
import { PipelineResultType, ok } from '../pipelines/results'
import { createValidateAiEventTokensStep } from './validate-ai-event-tokens'

const VALID_TOKEN_VALUES: [unknown, string][] = [
    [100, 'positive integer'],
    [0, 'zero'],
    [-100, 'negative integer'],
    [100.5, 'positive decimal'],
    [-100.5, 'negative decimal'],
    ['100', 'string integer'],
    ['100.5', 'string decimal'],
    ['-100', 'negative string integer'],
    ['0', 'string zero'],
    ['', 'empty string'],
    [null, 'null'],
    [undefined, 'undefined'],
]

const INVALID_TOKEN_VALUES: [unknown, string][] = [
    [NaN, 'NaN'],
    [Infinity, 'Infinity'],
    [-Infinity, 'negative Infinity'],
    ['invalid', 'non-numeric string'],
    ['100abc', 'string with trailing chars'],
    ['abc100', 'string with leading chars'],
    [true, 'boolean true'],
    [false, 'boolean false'],
]

const NORMALIZABLE_TOKEN_VALUES: [unknown, number, string][] = [
    [{ total: 100 }, 100, 'object with numeric total'],
    [{ total: 0 }, 0, 'object with zero total'],
    [{ total: 100.5, noCache: 100.5, cacheRead: 0 }, 100.5, 'Vercel V3 input tokens'],
    [{ total: 50, text: 50, reasoning: 0 }, 50, 'Vercel V3 output tokens'],
]

const NON_NORMALIZABLE_OBJECT_VALUES: [unknown, string][] = [
    [{}, 'empty object'],
    [{ value: 100 }, 'object without total'],
    [[], 'empty array'],
    [[100], 'array with number'],
]

const TOKEN_PROPERTIES = [
    '$ai_input_tokens',
    '$ai_output_tokens',
    '$ai_reasoning_tokens',
    '$ai_cache_read_input_tokens',
    '$ai_cache_creation_input_tokens',
] as const

const AI_EVENT_TYPES = ['$ai_generation', '$ai_embedding', '$ai_span', '$ai_trace', '$ai_metric', '$ai_feedback']

const NON_AI_EVENT_TYPES = ['$pageview', '$identify', 'custom_event', '$exception']

describe('createValidateAiEventTokensStep', () => {
    const step = createValidateAiEventTokensStep()

    const createEvent = (eventName: string, properties?: Record<string, unknown>) => ({
        event: createTestPipelineEvent({
            event: eventName,
            distinct_id: 'user123',
            team_id: 1,
            properties,
        }),
    })

    const expectAllowed = async (input: ReturnType<typeof createEvent>) => {
        const result = await step(input)
        expect(result).toEqual(ok(input))
    }

    const expectNulledWithWarning = async (input: ReturnType<typeof createEvent>, property: string, value: unknown) => {
        const result = await step(input)
        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.event.properties?.[property]).toBeNull()
            expect(result.warnings).toHaveLength(1)
            expect(result.warnings[0]).toMatchObject({
                type: 'invalid_ai_token_property',
                details: { property, valueType: typeof value },
            })
        }
    }

    it.each(NON_AI_EVENT_TYPES)('allows non-AI %s events regardless of invalid token properties', async (eventName) => {
        const input = createEvent(eventName, {
            $ai_input_tokens: 'invalid',
            $ai_output_tokens: 'invalid',
            $ai_reasoning_tokens: 'invalid',
            $ai_cache_read_input_tokens: {},
            $ai_cache_creation_input_tokens: {},
        })
        await expectAllowed(input)
    })

    describe.each(AI_EVENT_TYPES)('for %s', (eventType) => {
        describe.each(TOKEN_PROPERTIES)('with %s', (property) => {
            it.each(VALID_TOKEN_VALUES)('allows valid value: %p (%s)', async (value) => {
                const input = createEvent(eventType, { [property]: value })
                await expectAllowed(input)
            })

            it.each(INVALID_TOKEN_VALUES)('nulls invalid value with warning: %p (%s)', async (value) => {
                const input = createEvent(eventType, { [property]: value })
                await expectNulledWithWarning(input, property, value)
            })

            it.each(NORMALIZABLE_TOKEN_VALUES)(
                'normalizes object with total: %p -> %p (%s)',
                async (value, expected) => {
                    const input = createEvent(eventType, { [property]: value })
                    const result = await step(input)
                    expect(result.type).toBe(PipelineResultType.OK)
                    if (result.type === PipelineResultType.OK) {
                        expect(result.value.event.properties?.[property]).toBe(expected)
                        expect(result.warnings).toHaveLength(0)
                    }
                }
            )

            it.each(NON_NORMALIZABLE_OBJECT_VALUES)(
                'nulls non-normalizable object with warning: %p (%s)',
                async (value) => {
                    const input = createEvent(eventType, { [property]: value })
                    const result = await step(input)
                    expect(result.type).toBe(PipelineResultType.OK)
                    if (result.type === PipelineResultType.OK) {
                        expect(result.value.event.properties?.[property]).toBeNull()
                        expect(result.warnings).toHaveLength(1)
                    }
                }
            )
        })
    })

    describe('normalization edge cases', () => {
        it('normalizes object with total that is NaN to null with warning', async () => {
            const input = createEvent('$ai_generation', { $ai_input_tokens: { total: NaN } })
            const result = await step(input)
            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.event.properties?.['$ai_input_tokens']).toBeNull()
                expect(result.warnings).toHaveLength(1)
            }
        })

        it('normalizes object with non-numeric total to null with warning', async () => {
            const input = createEvent('$ai_generation', { $ai_input_tokens: { total: 'not a number' } })
            const result = await step(input)
            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.event.properties?.['$ai_input_tokens']).toBeNull()
                expect(result.warnings).toHaveLength(1)
            }
        })

        it('does not add missing token properties to the event', async () => {
            const input = createEvent('$ai_generation', { $ai_input_tokens: 100 })
            const result = await step(input)
            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.event.properties?.['$ai_input_tokens']).toBe(100)
                expect('$ai_output_tokens' in (result.value.event.properties ?? {})).toBe(false)
                expect('$ai_reasoning_tokens' in (result.value.event.properties ?? {})).toBe(false)
            }
        })
    })
})
