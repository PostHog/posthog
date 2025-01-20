import { PluginEvent } from '@posthog/plugin-scaffold'

import { processAiEvent } from '../../../src/worker/ingestion/event-pipeline/processAiEvent'

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
            expect(result.properties.$ai_total_cost_usd).toBeDefined()
            expect(result.properties.$ai_input_cost_usd).toBeDefined()
            expect(result.properties.$ai_output_cost_usd).toBeDefined()
        })

        it('matches $ai_embedding events', () => {
            event.event = '$ai_embedding'
            const result = processAiEvent(event)
            expect(result.properties.$ai_total_cost_usd).toBeDefined()
            expect(result.properties.$ai_input_cost_usd).toBeDefined()
            expect(result.properties.$ai_output_cost_usd).toBeDefined()
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
            expect(result.properties.$ai_total_cost_usd).toBeDefined()
            expect(result.properties.$ai_input_cost_usd).toBeDefined()
            expect(result.properties.$ai_output_cost_usd).toBeDefined()
        })

        it('matches model variants', () => {
            event.properties.$ai_model = 'gpt-4-turbo-0125-preview'
            const result = processAiEvent(event)
            expect(result.properties.$ai_total_cost_usd).toBeDefined()
            expect(result.properties.$ai_input_cost_usd).toBeDefined()
            expect(result.properties.$ai_output_cost_usd).toBeDefined()
        })

        it('handles unknown models', () => {
            event.properties.$ai_model = 'unknown-model'
            const result = processAiEvent(event)
            expect(result.properties.$ai_total_cost_usd).toBeUndefined()
            expect(result.properties.$ai_input_cost_usd).toBeUndefined()
            expect(result.properties.$ai_output_cost_usd).toBeUndefined()
        })
    })

    describe('cost calculation', () => {
        it('calculates correct cost for prompt and completion tokens', () => {
            const result = processAiEvent(event)
            expect(result.properties.$ai_total_cost_usd).toBeGreaterThan(0)
        })

        it('handles missing token counts', () => {
            delete event.properties.$ai_input_tokens
            delete event.properties.$ai_output_tokens
            const result = processAiEvent(event)
            expect(result.properties.$ai_total_cost_usd).toBe(0)
            expect(result.properties.$ai_input_cost_usd).toBe(0)
            expect(result.properties.$ai_output_cost_usd).toBe(0)
        })

        it('handles zero token counts', () => {
            event.properties.$ai_input_tokens = 0
            event.properties.$ai_output_tokens = 0
            const result = processAiEvent(event)
            expect(result.properties.$ai_total_cost_usd).toBe(0)
            expect(result.properties.$ai_input_cost_usd).toBe(0)
            expect(result.properties.$ai_output_cost_usd).toBe(0)
        })
    })

    describe('provider handling', () => {
        it('processes OpenAI events', () => {
            event.properties.$ai_provider = 'openai'
            const result = processAiEvent(event)
            expect(result.properties.$ai_total_cost_usd).toBeDefined()
            expect(result.properties.$ai_input_cost_usd).toBeDefined()
            expect(result.properties.$ai_output_cost_usd).toBeDefined()
        })

        it('processes Anthropic events', () => {
            event.properties.$ai_provider = 'anthropic'
            event.properties.$ai_model = 'claude-2'
            const result = processAiEvent(event)
            expect(result.properties.$ai_total_cost_usd).toBeDefined()
            expect(result.properties.$ai_input_cost_usd).toBeDefined()
            expect(result.properties.$ai_output_cost_usd).toBeDefined()
        })
    })

    describe('error handling', () => {
        it('handles missing required properties', () => {
            delete event.properties.$ai_model
            const result = processAiEvent(event)
            expect(result.properties.$ai_total_cost_usd).toBeUndefined()
            expect(result.properties.$ai_input_cost_usd).toBeUndefined()
            expect(result.properties.$ai_output_cost_usd).toBeUndefined()
        })
    })
})
