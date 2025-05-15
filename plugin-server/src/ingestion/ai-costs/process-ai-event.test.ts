import { PluginEvent } from '@posthog/plugin-scaffold'

import { processAiEvent } from './process-ai-event'
import { costsByModel } from './providers'

jest.mock('./providers', () => {
    const originalProviders = jest.requireActual('./providers')
    return {
        ...originalProviders,
        costsByModel: {
            testing_model: { model: 'testing_model', cost: { prompt_token: 0.1, completion_token: 0.1 } },
            'gpt-4': { model: 'gpt-4', cost: { prompt_token: 0.2, completion_token: 0.2 } },
            'gpt-4-0125-preview': { model: 'gpt-4-0125-preview', cost: { prompt_token: 0.3, completion_token: 0.3 } },
            'mistral-7b-instruct-v0.1': {
                model: 'mistral-7b-instruct-v0.1',
                cost: { prompt_token: 0.4, completion_token: 0.4 },
            },
            'gpt-4o-mini': { model: 'gpt-4o-mini', cost: { prompt_token: 0.5, completion_token: 0.5 } },
            'claude-2': { model: 'claude-2', cost: { prompt_token: 0.6, completion_token: 0.6 } },
            'gemini-2.5-pro-preview': {
                model: 'gemini-2.5-pro-preview',
                cost: { prompt_token: 0.7, completion_token: 0.7 },
            },
            'gemini-2.5-pro-preview:large': {
                model: 'gemini-2.5-pro-preview:large',
                cost: { prompt_token: 0.8, completion_token: 0.8 },
            },
            'gpt-4.1': { model: 'gpt-4.1', cost: { prompt_token: 0.9, completion_token: 0.9 } },
        },
    }
})

describe('processAiEvent()', () => {
    let event: PluginEvent

    beforeEach(() => {
        event = {
            distinct_id: 'test_id',
            team_id: 1,
            uuid: 'test-uuid',
            timestamp: '2024-01-01T00:00:00.000Z',
            event: '$ai_generation',
            properties: {
                $ai_model: 'gpt-4',
                $ai_provider: 'openai',
                $ai_input_tokens: 100,
                $ai_output_tokens: 50,
            },
            ip: '127.0.0.1',
            site_url: 'https://test.com',
            now: '2024-01-01T00:00:00.000Z',
        } as PluginEvent
    })

    describe('event matching', () => {
        it('matches $ai_generation events', () => {
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBeTruthy()
            expect(result.properties!.$ai_input_cost_usd).toBeTruthy()
            expect(result.properties!.$ai_output_cost_usd).toBeTruthy()
        })

        it('matches $ai_embedding events', () => {
            event.event = '$ai_embedding'
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBeTruthy()
            expect(result.properties!.$ai_input_cost_usd).toBeTruthy()
            expect(result.properties!.$ai_output_cost_usd).toBeDefined()
        })

        it('does not match other events', () => {
            event.event = '$other_event'
            const result = processAiEvent(event)
            expect(result).toEqual(event)
        })
    })

    describe('model matching', () => {
        it('matches exact model names', () => {
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBeDefined()
            expect(result.properties!.$ai_input_cost_usd).toBeDefined()
            expect(result.properties!.$ai_output_cost_usd).toBeDefined()
        })

        it('matches model variants', () => {
            event.properties!.$ai_model = 'gpt-4-turbo-0125-preview'
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBeDefined()
            expect(result.properties!.$ai_input_cost_usd).toBeDefined()
            expect(result.properties!.$ai_output_cost_usd).toBeDefined()
        })

        it('handles unknown models', () => {
            event.properties!.$ai_model = 'unknown-model'
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBeUndefined()
            expect(result.properties!.$ai_input_cost_usd).toBeUndefined()
            expect(result.properties!.$ai_output_cost_usd).toBeUndefined()
        })
    })

    describe('cost calculation', () => {
        it('calculates correct cost for prompt and completion tokens', () => {
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBeGreaterThan(0)
        })

        it('handles missing token counts', () => {
            delete event.properties!.$ai_input_tokens
            delete event.properties!.$ai_output_tokens
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBe(0)
            expect(result.properties!.$ai_input_cost_usd).toBe(0)
            expect(result.properties!.$ai_output_cost_usd).toBe(0)
        })

        it('handles zero token counts', () => {
            event.properties!.$ai_input_tokens = 0
            event.properties!.$ai_output_tokens = 0
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBe(0)
            expect(result.properties!.$ai_input_cost_usd).toBe(0)
            expect(result.properties!.$ai_output_cost_usd).toBe(0)
        })
    })

    describe('provider handling', () => {
        it('processes OpenAI events', () => {
            event.properties!.$ai_provider = 'openai'
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBeDefined()
            expect(result.properties!.$ai_input_cost_usd).toBeDefined()
            expect(result.properties!.$ai_output_cost_usd).toBeDefined()
        })

        it('processes Anthropic events', () => {
            event.properties!.$ai_provider = 'anthropic'
            event.properties!.$ai_model = 'claude-2'
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBeDefined()
            expect(result.properties!.$ai_input_cost_usd).toBeDefined()
            expect(result.properties!.$ai_output_cost_usd).toBeDefined()
        })
    })

    describe('model parameters', () => {
        it('dont extract core model parameters if not present', () => {
            const result = processAiEvent(event)
            expect(result.properties!.$ai_temperature).toBeUndefined()
            expect(result.properties!.$ai_max_tokens).toBeUndefined()
            expect(result.properties!.$ai_stream).toBeUndefined()
        })

        it('extracts core model parameters if present', () => {
            event.properties!.$ai_model_parameters = {
                temperature: 0.5,
                max_completion_tokens: 100,
                stream: false,
            }
            const result = processAiEvent(event)
            expect(result.properties!.$ai_temperature).toBe(0.5)
            expect(result.properties!.$ai_max_tokens).toBe(100)
            expect(result.properties!.$ai_stream).toBe(false)
        })
    })

    describe('error handling', () => {
        it('handles missing required properties', () => {
            delete event.properties!.$ai_model
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBeUndefined()
            expect(result.properties!.$ai_input_cost_usd).toBeUndefined()
            expect(result.properties!.$ai_output_cost_usd).toBeUndefined()
        })
    })

    describe('smoke test every model', () => {
        it.each(Object.keys(costsByModel))('processes %s', (model) => {
            event.properties!.$ai_model = model
            const result = processAiEvent(event)
            expect({
                $ai_total_cost_usd: result.properties!.$ai_total_cost_usd,
                $ai_input_cost_usd: result.properties!.$ai_input_cost_usd,
                $ai_output_cost_usd: result.properties!.$ai_output_cost_usd,
            }).toMatchSnapshot()
        })
    })

    describe('openai cache handling', () => {
        it('handles cache read and write tokens with correct cost calculation', () => {
            event.properties!.$ai_provider = 'openai'
            event.properties!.$ai_model = 'testing_model'
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50
            event.properties!.$ai_cache_read_input_tokens = 40

            const result = processAiEvent(event)

            // For testing_model: prompt_token = 0.1, completion_token = 0.1
            // Input cost: (40 * 0.1 * 0.5) + (60 * 0.1) = 2 + 6 = 8
            // Output cost: 50 * 0.1 = 5
            // Total cost: 8 + 5 = 13
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(8, 2)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(5, 2)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(13, 2)
        })

        it('handles zero cache tokens correctly', () => {
            event.properties!.$ai_provider = 'openai'
            event.properties!.$ai_model = 'testing_model'
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50
            event.properties!.$ai_cache_read_input_tokens = 0

            const result = processAiEvent(event)

            // Input cost: 100 * 0.1 = 10
            // Output cost: 50 * 0.1 = 5
            // Total cost: 10 + 5 = 15
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(10, 2)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(5, 2)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(15, 2)
        })
    })

    describe('anthropic cache handling', () => {
        it('handles cache read and write tokens with correct cost calculation', () => {
            event.properties!.$ai_provider = 'anthropic'
            event.properties!.$ai_model = 'testing_model'
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50
            event.properties!.$ai_cache_read_input_tokens = 1000
            event.properties!.$ai_cache_creation_input_tokens = 20

            const result = processAiEvent(event)

            // For testing_model: prompt_token = 0.1, completion_token = 0.1
            // Write cost: 20 * 0.1 * 1.25 = 2.5
            // Read cost: 1000 * 0.1 * 0.1 = 10
            // Uncached cost: 100 * 0.1 = 10
            // Input cost: 2.5 + 10 + 10 = 22.5
            // Output cost: 50 * 0.1 = 5
            // Total cost: 22.5 + 5 = 27.5
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(22.5, 2)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(5, 2)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(27.5, 2)
        })

        it('handles zero cache tokens correctly', () => {
            event.properties!.$ai_provider = 'anthropic'
            event.properties!.$ai_model = 'testing_model'
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50
            event.properties!.$ai_cache_read_input_tokens = 0
            event.properties!.$ai_cache_creation_input_tokens = 0

            const result = processAiEvent(event)

            // Input cost: 100 * 0.1 = 10
            // Output cost: 50 * 0.1 = 5
            // Total cost: 10 + 5 = 15
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(10, 2)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(5, 2)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(15, 2)
        })
    })

    describe('gemini 2.5 pro preview', () => {
        it('handles the seperate price for lage prompts', () => {
            const event1 = {
                ...event,
                properties: {
                    ...event.properties,
                    $ai_model: 'gemini-2.5-pro-preview',
                    $ai_input_tokens: 200001,
                },
            }

            const event2 = {
                ...event,
                properties: {
                    ...event.properties,
                    $ai_model: 'gemini-2.5-pro-preview',
                    $ai_input_tokens: 199999,
                },
            }

            const result1 = processAiEvent(event1)
            const result2 = processAiEvent(event2)

            expect(result1.properties!.$ai_total_cost_usd).toBeDefined()
            expect(result1.properties!.$ai_input_cost_usd).toBeDefined()
            expect(result1.properties!.$ai_output_cost_usd).toBeDefined()
            expect(result2.properties!.$ai_input_cost_usd).toBeDefined()
            expect(result2.properties!.$ai_output_cost_usd).toBeDefined()
            expect(result1.properties!.$ai_input_cost_usd).toBeGreaterThan(result2.properties!.$ai_input_cost_usd)
            expect(result1.properties!.$ai_output_cost_usd).toBeGreaterThan(result2.properties!.$ai_output_cost_usd)
            expect(result1.properties!.$ai_total_cost_usd).toBeGreaterThan(result2.properties!.$ai_total_cost_usd)
        })
    })

    describe('advanced model matching logic specific tests', () => {
        const inputTokens = 100
        const outputTokens = 50

        beforeEach(() => {
            event.properties = {
                ...event.properties,
                $ai_provider: 'openai',
                $ai_input_tokens: inputTokens,
                $ai_output_tokens: outputTokens,
                $ai_model: undefined,
                $ai_input_cost_usd: undefined,
                $ai_output_cost_usd: undefined,
                $ai_total_cost_usd: undefined,
            }
        })

        it('correctly matches a more specific input model to its known base (Rule 2)', () => {
            event.properties!.$ai_model = 'testing_model-suffix-123'
            const result = processAiEvent(event)

            const expectedInputCost = inputTokens * 0.1 // 100 * 0.1
            const expectedOutputCost = outputTokens * 0.1 // 50 * 0.1
            expect(result.properties!.$ai_input_cost_usd).toBe(expectedInputCost)
            expect(result.properties!.$ai_output_cost_usd).toBe(expectedOutputCost)
            expect(result.properties!.$ai_total_cost_usd).toBe(expectedInputCost + expectedOutputCost)
        })

        it('matches the longest known model name that is a substring of a specific input model (Rule 2 refinement)', () => {
            event.properties!.$ai_model = 'gpt-4-0125-preview-custom-suffix'
            const result = processAiEvent(event)

            const modelCost = costsByModel['gpt-4-0125-preview'].cost // p:0.3, c:0.3
            const expectedInputCost = inputTokens * modelCost.prompt_token // 100 * 0.3
            const expectedOutputCost = outputTokens * modelCost.completion_token // 50 * 0.3

            expect(result.properties!.$ai_input_cost_usd).toBe(expectedInputCost)
            expect(result.properties!.$ai_output_cost_usd).toBe(expectedOutputCost)
            expect(result.properties!.$ai_total_cost_usd).toBe(expectedInputCost + expectedOutputCost)
        })

        it('matches a general input model to a more specific known model (Rule 3, first found)', () => {
            event.properties!.$ai_model = 'mistral-7b-instruct'
            const result = processAiEvent(event)

            const modelCost = costsByModel['mistral-7b-instruct-v0.1'].cost // p:0.4, c:0.4
            const expectedInputCost = inputTokens * modelCost.prompt_token // 100 * 0.4
            const expectedOutputCost = outputTokens * modelCost.completion_token // 50 * 0.4

            expect(result.properties!.$ai_input_cost_usd).toBe(expectedInputCost)
            expect(result.properties!.$ai_output_cost_usd).toBe(expectedOutputCost)
            expect(result.properties!.$ai_total_cost_usd).toBe(expectedInputCost + expectedOutputCost)
        })

        it('correctly prioritizes Rule 2 (input specific) over Rule 3 (input general) for ambiguous cases like "gpt-4o"', () => {
            event.properties!.$ai_model = 'gpt-4o'
            const result = processAiEvent(event)

            const gpt4Cost = costsByModel['gpt-4'].cost // p:0.2, c:0.2
            const expectedInputCost = inputTokens * gpt4Cost.prompt_token // 100 * 0.2
            const expectedOutputCost = outputTokens * gpt4Cost.completion_token // 50 * 0.2

            expect(result.properties!.$ai_input_cost_usd).toBe(expectedInputCost)
            expect(result.properties!.$ai_output_cost_usd).toBe(expectedOutputCost)
            expect(result.properties!.$ai_total_cost_usd).toBe(expectedInputCost + expectedOutputCost)
        })

        it('correctly prioritizes 4.1 over 4 in long case', () => {
            event.properties!.$ai_model = 'gpt-4.1-preview-0502'
            const result = processAiEvent(event)

            const gpt41Cost = costsByModel['gpt-4.1'].cost // p:0.9, c:0.9
            const expectedInputCost = inputTokens * gpt41Cost.prompt_token // 100 * 0.9
            const expectedOutputCost = outputTokens * gpt41Cost.completion_token // 50 * 0.9

            expect(result.properties!.$ai_input_cost_usd).toBe(expectedInputCost)
            expect(result.properties!.$ai_output_cost_usd).toBe(expectedOutputCost)
            expect(result.properties!.$ai_total_cost_usd).toBe(expectedInputCost + expectedOutputCost)
        })

        it('returns undefined costs if no matching rule applies after all checks', () => {
            event.properties!.$ai_model = 'completely_unknown_model_structure_123_xyz_very_unique'
            const result = processAiEvent(event)
            expect(result.properties!.$ai_input_cost_usd).toBeUndefined()
            expect(result.properties!.$ai_output_cost_usd).toBeUndefined()
            expect(result.properties!.$ai_total_cost_usd).toBeUndefined()
        })
    })
})
