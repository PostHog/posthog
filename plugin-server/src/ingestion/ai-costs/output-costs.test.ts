import { PluginEvent } from '@posthog/plugin-scaffold'

import { calculateOutputCost } from './output-costs'
import { ModelRow } from './providers/types'

// Helper function to create a PluginEvent with default values
function createAIEvent(properties?: Record<string, any>): PluginEvent {
    return {
        event: '$ai_generation',
        properties: properties || {},
        ip: '',
        site_url: '',
        team_id: 0,
        now: '',
        distinct_id: '',
        uuid: '',
        timestamp: '',
    }
}

// Helper function to create a ModelRow with defaults
function createModel(
    model: string,
    provider?: string,
    promptTokenCost?: number,
    completionTokenCost?: number
): ModelRow {
    return {
        model,
        ...(provider && { provider }),
        cost: {
            prompt_token: promptTokenCost ?? 0.000001,
            completion_token: completionTokenCost ?? 0.000002,
        },
    }
}

// Helper function to assert cost calculation
function expectCost(result: string, expectedCost: number, precision: number = 6): void {
    expect(parseFloat(result)).toBeCloseTo(expectedCost, precision)
}

describe('calculateOutputCost()', () => {
    describe('basic output cost calculation', () => {
        const basicModel = createModel('gpt-4', 'openai', 0.00003, 0.00006)

        it('calculates output cost without reasoning tokens', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-4',
                $ai_output_tokens: 500,
            })

            const result = calculateOutputCost(event, basicModel)

            expectCost(result, 0.03) // 500 * 0.00006 = 0.03
        })

        it.each([
            { tokens: 0, expectedResult: '0', description: 'returns 0 when output tokens is 0' },
            { tokens: undefined, expectedResult: '0', description: 'returns 0 when output tokens is undefined' },
        ])('$description', ({ tokens, expectedResult }) => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-4',
                ...(tokens !== undefined && { $ai_output_tokens: tokens }),
            })

            const result = calculateOutputCost(event, basicModel)

            expect(result).toBe(expectedResult)
        })

        it('handles very large output token counts', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-4',
                $ai_output_tokens: 1e10,
            })

            const result = calculateOutputCost(event, basicModel)

            expect(parseFloat(result)).toBeGreaterThan(0)
        })
    })

    describe('gemini 2.5 models - reasoning token handling', () => {
        const gemini25ProModel = createModel('gemini-2.5-pro', 'google', 0.00000125, 0.00001)
        const gemini25FlashModel = createModel('gemini-2.5-flash', 'google', 3e-7, 0.0000025)

        it.each([
            {
                model: 'gemini-2.5-pro',
                modelRow: gemini25ProModel,
                outputTokens: 100,
                reasoningTokens: 200,
                expectedCost: 0.003,
                description: 'includes reasoning tokens for gemini-2.5-pro',
            },
            {
                model: 'gemini-2.5-flash',
                modelRow: gemini25FlashModel,
                outputTokens: 50,
                reasoningTokens: 150,
                expectedCost: 0.0005,
                description: 'includes reasoning tokens for gemini-2.5-flash',
            },
        ])('$description', ({ model, modelRow, outputTokens, reasoningTokens, expectedCost }) => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: model,
                $ai_output_tokens: outputTokens,
                $ai_reasoning_tokens: reasoningTokens,
            })

            const result = calculateOutputCost(event, modelRow)

            expectCost(result, expectedCost)
        })

        it.each([
            {
                reasoningTokens: undefined,
                description: 'handles undefined reasoning tokens',
            },
            {
                reasoningTokens: 0,
                description: 'handles zero reasoning tokens',
            },
        ])('$description for gemini-2.5', ({ reasoningTokens }) => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-pro',
                $ai_output_tokens: 100,
                ...(reasoningTokens !== undefined && { $ai_reasoning_tokens: reasoningTokens }),
            })

            const result = calculateOutputCost(event, gemini25ProModel)

            expectCost(result, 0.001) // 100 * 0.00001 = 0.001
        })

        it.each([
            { modelName: 'GEMINI-2.5-PRO', description: 'is case-insensitive for model matching' },
            { modelName: 'gemini-2.5-pro-preview-0514', description: 'handles gemini-2.5 variants with suffixes' },
        ])('$description', ({ modelName }) => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: modelName,
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: 200,
            })

            const result = calculateOutputCost(event, gemini25ProModel)

            expectCost(result, 0.003) // Should include reasoning tokens
        })

        it('handles very large reasoning token counts', () => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-pro',
                $ai_output_tokens: 1000,
                $ai_reasoning_tokens: 1e9,
            })

            const result = calculateOutputCost(event, gemini25ProModel)

            expect(parseFloat(result)).toBeGreaterThan(10000)
        })
    })

    describe('gemini 2.0 models - no reasoning token handling', () => {
        const gemini20FlashModel = createModel('gemini-2.0-flash', 'google', 1e-7, 4e-7)

        it.each([
            { modelName: 'gemini-2.0-flash', description: 'does not include reasoning tokens for gemini-2.0' },
            {
                modelName: 'gemini-2.0-flash-001',
                description: 'does not include reasoning tokens for gemini-2.0-flash-001',
            },
        ])('$description', ({ modelName }) => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: modelName,
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: 200,
            })

            const result = calculateOutputCost(event, gemini20FlashModel)

            // Only output tokens, no reasoning: 100 * 4e-7 = 0.00004
            expectCost(result, 0.00004, 7)
        })
    })

    describe('non-gemini models - no reasoning token handling', () => {
        const testCases = [
            {
                name: 'OpenAI',
                model: 'gpt-4o',
                provider: 'openai',
                promptCost: 0.0000025,
                completionCost: 0.00001,
                expectedCost: 0.001,
            },
            {
                name: 'Anthropic',
                model: 'claude-3-5-sonnet',
                provider: 'anthropic',
                promptCost: 0.000003,
                completionCost: 0.000015,
                expectedCost: 0.0015,
            },
            {
                name: 'o1',
                model: 'o1-mini',
                provider: 'openai',
                promptCost: 0.0000011,
                completionCost: 0.0000044,
                expectedCost: 0.00044,
            },
            {
                name: 'custom',
                model: 'custom-model',
                provider: 'custom',
                promptCost: 0.000001,
                completionCost: 0.000002,
                expectedCost: 0.0002,
            },
        ]

        it.each(testCases)(
            'does not include reasoning tokens for $name models',
            ({ model, provider, promptCost, completionCost, expectedCost }) => {
                const modelRow = createModel(model, provider, promptCost, completionCost)
                const event = createAIEvent({
                    $ai_provider: provider,
                    $ai_model: model,
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                })

                const result = calculateOutputCost(event, modelRow)

                // Only output tokens: 100 * completionCost
                expectCost(result, expectedCost)
            }
        )
    })

    describe('edge cases', () => {
        const testModel = createModel('test-model')

        it('returns 0 when properties is undefined', () => {
            const event = {
                ...createAIEvent(),
                properties: undefined,
            }

            const result = calculateOutputCost(event, testModel)

            expect(result).toBe('0')
        })

        it.each([
            { value: null, description: 'handles null output tokens' },
            { value: undefined, description: 'handles undefined output tokens (via empty properties)' },
        ])('$description', ({ value }) => {
            const event = createAIEvent(value === undefined ? {} : { $ai_output_tokens: value as any })

            const result = calculateOutputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('handles null reasoning tokens for gemini-2.5', () => {
            const gemini25Model = createModel('gemini-2.5-pro', undefined, 0.00000125, 0.00001)
            const event = createAIEvent({
                $ai_model: 'gemini-2.5-pro',
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: null as any,
            })

            const result = calculateOutputCost(event, gemini25Model)

            // Should treat null as 0: 100 * 0.00001 = 0.001
            expectCost(result, 0.001)
        })

        it('handles negative output tokens', () => {
            const event = createAIEvent({
                $ai_output_tokens: -100,
            })

            const result = calculateOutputCost(event, testModel)

            // Should calculate even with negative (though invalid in practice)
            expect(parseFloat(result)).toBeLessThan(0)
        })

        it('handles negative reasoning tokens for gemini-2.5', () => {
            const gemini25Model = createModel('gemini-2.5-pro', undefined, 0.00000125, 0.00001)
            const event = createAIEvent({
                $ai_model: 'gemini-2.5-pro',
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: -50,
            })

            const result = calculateOutputCost(event, gemini25Model)

            // (100 + (-50)) * 0.00001 = 50 * 0.00001 = 0.0005
            expectCost(result, 0.0005)
        })

        it('handles missing model field for reasoning check', () => {
            const gemini25Model = createModel('gemini-2.5-pro', undefined, 0.00000125, 0.00001)
            const event = createAIEvent({
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: 200,
            })

            const result = calculateOutputCost(event, gemini25Model)

            // Without $ai_model, reasoning tokens won't be added
            // Only output tokens: 100 * 0.00001 = 0.001
            expectCost(result, 0.001)
        })

        it('handles gemini-2.5 model variant names', () => {
            const gemini25FlashModel = createModel('gemini-2.5-flash', 'google', 3e-7, 0.0000025)
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-flash-exp',
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: 200,
            })

            const result = calculateOutputCost(event, gemini25FlashModel)

            // Should include reasoning tokens: (100 + 200) * 0.0000025 = 0.00075
            expectCost(result, 0.00075)
        })
    })
})
