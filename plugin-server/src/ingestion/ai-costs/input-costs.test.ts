import { PluginEvent } from '@posthog/plugin-scaffold'

import { calculateInputCost } from './input-costs'
import { ModelRow } from './providers/types'

// Test helper functions
function createTestEvent(overrides: Partial<PluginEvent> = {}): PluginEvent {
    return {
        event: '$ai_generation',
        properties: {},
        ip: '',
        site_url: '',
        team_id: 0,
        now: '',
        distinct_id: '',
        uuid: '',
        timestamp: '',
        ...overrides,
    }
}

function createTestModel(overrides: Partial<ModelRow> = {}): ModelRow {
    return {
        model: 'test-model',
        cost: {
            prompt_token: 0.000001,
            completion_token: 0.000002,
        },
        ...overrides,
    }
}

function createAnthropicTestEvent(
    inputTokens: number,
    cacheReadTokens?: number,
    cacheWriteTokens?: number,
    additionalProps: Record<string, any> = {}
): PluginEvent {
    return createTestEvent({
        properties: {
            $ai_provider: 'anthropic',
            $ai_model: 'claude-3-5-sonnet',
            $ai_input_tokens: inputTokens,
            ...(cacheReadTokens !== undefined && { $ai_cache_read_input_tokens: cacheReadTokens }),
            ...(cacheWriteTokens !== undefined && { $ai_cache_creation_input_tokens: cacheWriteTokens }),
            ...additionalProps,
        },
    })
}

function createOpenAITestEvent(
    inputTokens: number,
    cacheReadTokens?: number,
    additionalProps: Record<string, any> = {}
): PluginEvent {
    return createTestEvent({
        properties: {
            $ai_provider: 'openai',
            $ai_model: 'gpt-4o',
            $ai_input_tokens: inputTokens,
            ...(cacheReadTokens !== undefined && { $ai_cache_read_input_tokens: cacheReadTokens }),
            ...additionalProps,
        },
    })
}

function createGeminiTestEvent(
    inputTokens: number,
    cacheReadTokens?: number,
    additionalProps: Record<string, any> = {}
): PluginEvent {
    return createTestEvent({
        properties: {
            $ai_provider: 'google',
            $ai_model: 'gemini-2.5-pro',
            $ai_input_tokens: inputTokens,
            ...(cacheReadTokens !== undefined && { $ai_cache_read_input_tokens: cacheReadTokens }),
            ...additionalProps,
        },
    })
}

function expectCostToBeCloseTo(actual: string | number, expected: number, precision: number = 6): void {
    expect(parseFloat(actual.toString())).toBeCloseTo(expected, precision)
}

// Common test models
const ANTHROPIC_MODEL: ModelRow = {
    model: 'claude-3-5-sonnet',
    provider: 'anthropic',
    cost: {
        prompt_token: 0.000003,
        completion_token: 0.000015,
        cache_read_token: 3e-7,
        cache_write_token: 0.00000375,
    },
}

const OPENAI_MODEL: ModelRow = {
    model: 'gpt-4o',
    provider: 'openai',
    cost: {
        prompt_token: 0.0000025,
        completion_token: 0.00001,
        cache_read_token: 0.00000125,
    },
}

const GEMINI_MODEL: ModelRow = {
    model: 'gemini-2.5-pro',
    provider: 'google',
    cost: {
        prompt_token: 0.00000125,
        completion_token: 0.00001,
        cache_read_token: 3.1e-7,
    },
}

describe('calculateInputCost()', () => {
    describe('anthropic provider - cache handling', () => {
        it('calculates cost with cache read tokens using explicit costs', () => {
            const event = createAnthropicTestEvent(1000, 500)
            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Read: 500 * 3e-7 = 0.00015
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00015 + 0.003 = 0.00315
            expectCostToBeCloseTo(result, 0.00315)
        })

        it('calculates cost with cache write tokens using explicit costs', () => {
            const event = createAnthropicTestEvent(1000, undefined, 300)
            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Write: 300 * 0.00000375 = 0.001125
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.001125 + 0.003 = 0.004125
            expectCostToBeCloseTo(result, 0.004125)
        })

        it('calculates cost with both read and write cache tokens', () => {
            const event = createAnthropicTestEvent(1000, 500, 300)
            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Write: 300 * 0.00000375 = 0.001125
            // Read: 500 * 3e-7 = 0.00015
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.001125 + 0.00015 + 0.003 = 0.004275
            expectCostToBeCloseTo(result, 0.004275)
        })

        it('uses 1.25x multiplier fallback for cache write when not defined', () => {
            const modelWithoutCacheWrite = createTestModel({
                model: 'claude-2',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000008,
                    completion_token: 0.000024,
                },
            })

            const event = createAnthropicTestEvent(1000, undefined, 200, {
                $ai_model: 'claude-2',
            })

            const result = calculateInputCost(event, modelWithoutCacheWrite)

            // Write: 200 * 0.000008 * 1.25 = 0.002
            // Regular: 1000 * 0.000008 = 0.008
            // Total: 0.002 + 0.008 = 0.01
            expectCostToBeCloseTo(result, 0.01)
        })

        it('uses 0.1x multiplier fallback for cache read when not defined', () => {
            const modelWithoutCacheRead = createTestModel({
                model: 'claude-2',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000008,
                    completion_token: 0.000024,
                },
            })

            const event = createAnthropicTestEvent(1000, 400, undefined, {
                $ai_model: 'claude-2',
            })

            const result = calculateInputCost(event, modelWithoutCacheRead)

            // Read: 400 * 0.000008 * 0.1 = 0.00032
            // Regular: 1000 * 0.000008 = 0.008
            // Total: 0.00032 + 0.008 = 0.00832
            expectCostToBeCloseTo(result, 0.00832)
        })

        it('handles zero cache tokens correctly', () => {
            const event = createAnthropicTestEvent(1000, 0, 0)
            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Regular: 1000 * 0.000003 = 0.003
            expectCostToBeCloseTo(result, 0.003)
        })

        it('handles undefined cache tokens correctly', () => {
            const event = createAnthropicTestEvent(1000)
            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Regular: 1000 * 0.000003 = 0.003
            expectCostToBeCloseTo(result, 0.003)
        })

        it('matches provider case-insensitively', () => {
            const event = createAnthropicTestEvent(1000, 500, undefined, {
                $ai_provider: 'ANTHROPIC',
            })

            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Should still use Anthropic path
            // Read: 500 * 3e-7 = 0.00015
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00315
            expectCostToBeCloseTo(result, 0.00315)
        })

        it('matches provider in model string', () => {
            const event = createTestEvent({
                properties: {
                    $ai_provider: 'gateway',
                    $ai_model: 'anthropic/claude-3-5-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_creation_input_tokens: 200,
                },
            })

            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Should use Anthropic path because model contains "anthropic"
            // Write: 200 * 0.00000375 = 0.00075
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00375
            expectCostToBeCloseTo(result, 0.00375)
        })
    })

    describe('openai provider - cache handling', () => {
        it('calculates cost with cache read tokens using explicit costs', () => {
            const event = createOpenAITestEvent(1000, 400)
            const result = calculateInputCost(event, OPENAI_MODEL)

            // Regular: (1000 - 400) * 0.0000025 = 600 * 0.0000025 = 0.0015
            // Read: 400 * 0.00000125 = 0.0005
            // Total: 0.0015 + 0.0005 = 0.002
            expectCostToBeCloseTo(result, 0.002)
        })

        it('uses 0.5x multiplier fallback when cache_read_token not defined', () => {
            const modelWithoutCacheRead = createTestModel({
                model: 'gpt-4',
                provider: 'openai',
                cost: {
                    prompt_token: 0.00003,
                    completion_token: 0.00006,
                },
            })

            const event = createOpenAITestEvent(1000, 400, { $ai_model: 'gpt-4' })
            const result = calculateInputCost(event, modelWithoutCacheRead)

            // Regular: (1000 - 400) * 0.00003 = 600 * 0.00003 = 0.018
            // Read: 400 * 0.00003 * 0.5 = 0.006
            // Total: 0.018 + 0.006 = 0.024
            expectCostToBeCloseTo(result, 0.024)
        })

        it('handles zero cache read tokens', () => {
            const event = createOpenAITestEvent(1000, 0)
            const result = calculateInputCost(event, OPENAI_MODEL)

            // Regular: 1000 * 0.0000025 = 0.0025
            expectCostToBeCloseTo(result, 0.0025)
        })

        it('handles undefined cache read tokens', () => {
            const event = createOpenAITestEvent(1000)
            const result = calculateInputCost(event, OPENAI_MODEL)

            // Regular: 1000 * 0.0000025 = 0.0025
            expectCostToBeCloseTo(result, 0.0025)
        })

        it('matches provider in model string for gateway', () => {
            const event = createTestEvent({
                properties: {
                    $ai_provider: 'gateway',
                    $ai_model: 'openai/gpt-4o',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 400,
                },
            })

            const result = calculateInputCost(event, OPENAI_MODEL)

            // Should use OpenAI/default path (not Anthropic)
            // Regular: (1000 - 400) * 0.0000025 = 0.0015
            // Read: 400 * 0.00000125 = 0.0005
            // Total: 0.002
            expectCostToBeCloseTo(result, 0.002)
        })
    })

    describe('gemini provider - cache handling', () => {
        it('calculates cost with cache read tokens using explicit costs', () => {
            const event = createGeminiTestEvent(10000, 4000)
            const result = calculateInputCost(event, GEMINI_MODEL)

            // Regular: (10000 - 4000) * 0.00000125 = 6000 * 0.00000125 = 0.0075
            // Read: 4000 * 3.1e-7 = 0.00124
            // Total: 0.0075 + 0.00124 = 0.00874
            expectCostToBeCloseTo(result, 0.00874)
        })

        it('handles zero cache read tokens', () => {
            const event = createGeminiTestEvent(10000, 0)
            const result = calculateInputCost(event, GEMINI_MODEL)

            // Regular: 10000 * 0.00000125 = 0.0125
            expectCostToBeCloseTo(result, 0.0125)
        })
    })

    describe('default provider - cache handling', () => {
        const customModel = createTestModel()

        it('uses 0.5x multiplier for cache read when provider unknown', () => {
            const event = createTestEvent({
                properties: {
                    $ai_provider: 'custom-provider',
                    $ai_model: 'custom-model',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 400,
                },
            })

            const result = calculateInputCost(event, customModel)

            // Regular: (1000 - 400) * 0.000001 = 0.0006
            // Read: 400 * 0.000001 * 0.5 = 0.0002
            // Total: 0.0008
            expectCostToBeCloseTo(result, 0.0008)
        })

        it('handles no provider field', () => {
            const event = createTestEvent({
                properties: {
                    $ai_model: 'custom-model',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 400,
                },
            })

            const result = calculateInputCost(event, customModel)

            // Should use default path
            // Regular: (1000 - 400) * 0.000001 = 0.0006
            // Read: 400 * 0.000001 * 0.5 = 0.0002
            // Total: 0.0008
            expectCostToBeCloseTo(result, 0.0008)
        })
    })

    describe('edge cases', () => {
        const testModel = createTestModel()

        it('returns 0 when properties is undefined', () => {
            const event = createTestEvent()
            const result = calculateInputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('returns 0 when input tokens is 0', () => {
            const event = createTestEvent({
                properties: { $ai_input_tokens: 0 },
            })

            const result = calculateInputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('handles undefined input tokens', () => {
            const event = createTestEvent({
                properties: { $ai_model: 'test-model' },
            })

            const result = calculateInputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('handles cache read tokens exceeding input tokens', () => {
            const event = createOpenAITestEvent(100, 200, { $ai_model: 'gpt-4' })
            const result = calculateInputCost(event, testModel)

            // Regular: (100 - 200) = -100, negative regular tokens
            // Read: 200 * 0.000001 * 0.5 = 0.0001
            // Regular: -100 * 0.000001 = -0.0001
            // Total: 0.0001 + (-0.0001) = 0
            expectCostToBeCloseTo(result, 0)
        })

        it('handles very large token counts', () => {
            const event = createOpenAITestEvent(1e10, 5e9, { $ai_model: 'gpt-4' })
            const result = calculateInputCost(event, testModel)

            expect(parseFloat(result)).toBeGreaterThan(0)
        })

        it('handles negative token counts gracefully', () => {
            const event = createOpenAITestEvent(-1000, undefined, { $ai_model: 'gpt-4' })
            const result = calculateInputCost(event, testModel)

            // Should calculate even with negative (though invalid in practice)
            expect(parseFloat(result)).toBeLessThan(0)
        })

        it('handles null cache token values', () => {
            const event = createTestEvent({
                properties: {
                    $ai_provider: 'anthropic',
                    $ai_model: 'claude-3-5-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: null as any,
                    $ai_cache_creation_input_tokens: null as any,
                },
            })

            const result = calculateInputCost(event, testModel)

            // Should treat null as 0
            expectCostToBeCloseTo(result, 0.001)
        })
    })

    describe('provider matching edge cases', () => {
        const testModel = createTestModel()

        it('handles undefined provider and model', () => {
            const event = createTestEvent({
                properties: { $ai_input_tokens: 1000 },
            })

            const result = calculateInputCost(event, testModel)

            // Should use default path
            expectCostToBeCloseTo(result, 0.001)
        })

        it('matches provider when only model contains provider name', () => {
            const event = createTestEvent({
                properties: {
                    $ai_model: 'anthropic-claude-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_creation_input_tokens: 200,
                },
            })

            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Should use Anthropic path because "anthropic" is in model
            // Write: 200 * 0.00000375 = 0.00075
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00375
            expectCostToBeCloseTo(result, 0.00375)
        })

        it('does not match partial provider names', () => {
            const anthropicModel = createTestModel({
                model: 'claude-3-5-sonnet',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000003,
                    completion_token: 0.000015,
                },
            })

            const event = createTestEvent({
                properties: {
                    $ai_provider: 'custom',
                    $ai_model: 'my-anthro-model',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 400,
                },
            })

            const result = calculateInputCost(event, anthropicModel)

            // Should NOT match Anthropic because "anthro" != "anthropic"
            // Uses default path: (1000-400) * 0.000003 + 400 * 0.000003 * 0.5
            expectCostToBeCloseTo(result, 0.0024)
        })

        it('is case-insensitive for provider matching in model string', () => {
            const anthropicModel = createTestModel({
                model: 'claude-3-5-sonnet',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000003,
                    completion_token: 0.000015,
                    cache_write_token: 0.00000375,
                },
            })

            const event = createTestEvent({
                properties: {
                    $ai_provider: 'gateway',
                    $ai_model: 'ANTHROPIC/claude-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_creation_input_tokens: 200,
                },
            })

            const result = calculateInputCost(event, anthropicModel)

            // Should match Anthropic path (case-insensitive)
            // Write: 200 * 0.00000375 = 0.00075
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00375
            expectCostToBeCloseTo(result, 0.00375)
        })
    })
})
