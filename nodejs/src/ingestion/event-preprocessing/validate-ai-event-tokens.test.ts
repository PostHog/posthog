import { createTestEventHeaders } from '~/tests/helpers/event-headers'

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
    [{}, 'empty object'],
    [{ value: 100 }, 'object with value'],
    [[], 'empty array'],
    [[100], 'array with number'],
    ['invalid', 'non-numeric string'],
    ['100abc', 'string with trailing chars'],
    ['abc100', 'string with leading chars'],
    [true, 'boolean true'],
    [false, 'boolean false'],
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
        event: {
            event: {
                event: eventName,
                distinct_id: 'user123',
                team_id: 1,
                ip: '127.0.0.1',
                site_url: 'https://example.com',
                now: '2021-01-01T00:00:00Z',
                uuid: '123e4567-e89b-12d3-a456-426614174000',
                properties,
            },
            headers: createTestEventHeaders({
                token: 'token123',
                distinct_id: 'user123',
                timestamp: '2021-01-01T00:00:00Z',
            }),
        },
    })

    const expectAllowed = async (input: ReturnType<typeof createEvent>) => {
        const result = await step(input)
        expect(result).toEqual(ok(input))
    }

    const expectDropped = async (input: ReturnType<typeof createEvent>, property: string, value: unknown) => {
        const result = await step(input)
        expect(result.type).toBe(PipelineResultType.DROP)
        if (result.type === PipelineResultType.DROP) {
            expect(result.reason).toBe(`invalid_ai_token_property:${property}`)
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

            it.each(INVALID_TOKEN_VALUES)('drops invalid value: %p (%s)', async (value) => {
                const input = createEvent(eventType, { [property]: value })
                await expectDropped(input, property, value)
            })
        })
    })
})
