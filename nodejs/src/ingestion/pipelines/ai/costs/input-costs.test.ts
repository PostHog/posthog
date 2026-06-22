import { PluginEvent } from '~/plugin-scaffold'

import { calculateInputCost, resolveCacheReportingExclusive } from './input-costs'
import { ResolvedModelCost } from './providers/types'
import { createAIEvent } from './test-helpers'

function createTestModel(overrides: Partial<ResolvedModelCost> = {}): ResolvedModelCost {
    return {
        model: 'test-model',
        provider: 'test',
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
    return createAIEvent({
        $ai_provider: 'anthropic',
        $ai_model: 'claude-3-5-sonnet',
        $ai_input_tokens: inputTokens,
        ...(cacheReadTokens !== undefined && { $ai_cache_read_input_tokens: cacheReadTokens }),
        ...(cacheWriteTokens !== undefined && { $ai_cache_creation_input_tokens: cacheWriteTokens }),
        ...additionalProps,
    })
}

function createOpenAITestEvent(
    inputTokens: number,
    cacheReadTokens?: number,
    additionalProps: Record<string, any> = {}
): PluginEvent {
    return createAIEvent({
        $ai_provider: 'openai',
        $ai_model: 'gpt-4o',
        $ai_input_tokens: inputTokens,
        ...(cacheReadTokens !== undefined && { $ai_cache_read_input_tokens: cacheReadTokens }),
        ...additionalProps,
    })
}

function createGeminiTestEvent(
    inputTokens: number,
    cacheReadTokens?: number,
    additionalProps: Record<string, any> = {}
): PluginEvent {
    return createAIEvent({
        $ai_provider: 'google',
        $ai_model: 'gemini-2.5-pro',
        $ai_input_tokens: inputTokens,
        ...(cacheReadTokens !== undefined && { $ai_cache_read_input_tokens: cacheReadTokens }),
        ...additionalProps,
    })
}

function expectCostToBeCloseTo(actual: string | number, expected: number, precision: number = 6): void {
    expect(parseFloat(actual.toString())).toBeCloseTo(expected, precision)
}

// Common test models
const ANTHROPIC_MODEL: ResolvedModelCost = {
    model: 'claude-3-5-sonnet',
    provider: 'anthropic',
    cost: {
        prompt_token: 0.000003,
        completion_token: 0.000015,
        cache_read_token: 3e-7,
        cache_write_token: 0.00000375,
    },
}

const OPENAI_MODEL: ResolvedModelCost = {
    model: 'gpt-4o',
    provider: 'openai',
    cost: {
        prompt_token: 0.0000025,
        completion_token: 0.00001,
        cache_read_token: 0.00000125,
    },
}

const GEMINI_MODEL: ResolvedModelCost = {
    model: 'gemini-2.5-pro',
    provider: 'google',
    cost: {
        prompt_token: 0.00000125,
        completion_token: 0.00001,
        cache_read_token: 3.1e-7,
    },
}

describe('resolveCacheReportingExclusive()', () => {
    it.each<{ name: string; properties: Record<string, any> | undefined; expected: boolean }>([
        {
            name: 'explicit true overrides auto-detect on OpenAI event',
            properties: { $ai_provider: 'openai', $ai_cache_reporting_exclusive: true },
            expected: true,
        },
        {
            name: 'explicit false overrides auto-detect on Anthropic event',
            properties: {
                $ai_provider: 'anthropic',
                $ai_model: 'claude-3-5-sonnet',
                $ai_cache_reporting_exclusive: false,
            },
            expected: false,
        },
        {
            name: 'explicit false overrides auto-detect on Claude via Vertex',
            properties: {
                $ai_provider: 'vertex',
                $ai_model: 'claude-haiku-4-5',
                $ai_cache_reporting_exclusive: false,
            },
            expected: false,
        },
        {
            name: 'auto-detects exclusive for Anthropic provider',
            properties: { $ai_provider: 'anthropic' },
            expected: true,
        },
        {
            name: 'auto-detects exclusive for Claude model via Vertex',
            properties: { $ai_provider: 'vertex', $ai_model: 'claude-haiku-4-5' },
            expected: true,
        },
        {
            name: 'auto-detects inclusive for Vercel gateway with valid token counts',
            properties: {
                $ai_provider: 'gateway',
                $ai_framework: 'vercel',
                $ai_model: 'anthropic/claude-sonnet-4.5',
                $ai_input_tokens: 14013,
                $ai_cache_read_input_tokens: 13306,
                $ai_cache_creation_input_tokens: 701,
            },
            expected: false,
        },
        {
            name: 'falls back to exclusive when Vercel gateway tokens are provably not inclusive',
            properties: {
                $ai_provider: 'gateway',
                $ai_framework: 'vercel',
                $ai_model: 'anthropic/claude-opus-4.6',
                $ai_input_tokens: 247,
                $ai_cache_read_input_tokens: 6287,
            },
            expected: true,
        },
        {
            name: 'auto-detects inclusive for OpenAI provider',
            properties: { $ai_provider: 'openai' },
            expected: false,
        },
        {
            name: 'returns false when event has no properties',
            properties: undefined,
            expected: false,
        },
    ])('$name', ({ properties, expected }) => {
        const event = {
            event: '$ai_generation',
            properties,
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        } as PluginEvent
        expect(resolveCacheReportingExclusive(event)).toBe(expected)
    })
})

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
            const event = createAIEvent({
                $ai_provider: 'gateway',
                $ai_model: 'anthropic/claude-3-5-sonnet',
                $ai_input_tokens: 1000,
                $ai_cache_creation_input_tokens: 200,
            })

            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Should use Anthropic path because model contains "anthropic"
            // Write: 200 * 0.00000375 = 0.00075
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00375
            expectCostToBeCloseTo(result, 0.00375)
        })

        it('uses inclusive token accounting for Vercel gateway Anthropic events', () => {
            const event = createAIEvent({
                $ai_provider: 'gateway',
                $ai_framework: 'vercel',
                $ai_model: 'anthropic/claude-sonnet-4.5',
                $ai_input_tokens: 14013,
                $ai_cache_read_input_tokens: 13306,
                $ai_cache_creation_input_tokens: 701,
            })

            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Read: 13306 * 3e-7 = 0.0039918
            // Write: 701 * 0.00000375 = 0.00262875
            // Uncached: (14013 - 13306 - 701) * 0.000003 = 0.000018
            // Total: 0.0039918 + 0.00262875 + 0.000018 = 0.00663855
            expectCostToBeCloseTo(result, 0.00663855, 8)
        })

        it('handles string token values correctly for inclusive accounting', () => {
            const event = createAIEvent({
                $ai_provider: 'gateway',
                $ai_framework: 'vercel',
                $ai_model: 'anthropic/claude-sonnet-4.5',
                $ai_input_tokens: '14013',
                $ai_cache_read_input_tokens: '13306',
                $ai_cache_creation_input_tokens: '701',
            })

            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Same as the numeric inclusive test — strings must produce identical results
            expectCostToBeCloseTo(result, 0.00663855, 8)
        })

        it('falls back to exclusive accounting when Vercel gateway tokens are provably not inclusive', () => {
            // When inputTokens < cacheReadTokens + cacheWriteTokens, the tokens can't be inclusive.
            // This happens when SDKs (e.g., posthog-ai) report Anthropic-style exclusive counts
            // through the Vercel gateway. Without this guard, uncachedTokens goes negative.
            const event = createAIEvent({
                $ai_provider: 'gateway',
                $ai_framework: 'vercel',
                $ai_model: 'anthropic/claude-opus-4.6',
                $ai_input_tokens: 247,
                $ai_cache_read_input_tokens: 6287,
            })

            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Exclusive accounting (same as standard Anthropic):
            // Read: 6287 * 3e-7 = 0.0018861
            // Regular: 247 * 0.000003 = 0.000741
            // Total: 0.0018861 + 0.000741 = 0.0026271
            expectCostToBeCloseTo(result, 0.0026271, 5)
            expect(parseFloat(result)).toBeGreaterThan(0)
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
            const event = createAIEvent({
                $ai_provider: 'gateway',
                $ai_model: 'openai/gpt-4o',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 400,
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
            const event = createAIEvent({
                $ai_provider: 'custom-provider',
                $ai_model: 'custom-model',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 400,
            })

            const result = calculateInputCost(event, customModel)

            // Regular: (1000 - 400) * 0.000001 = 0.0006
            // Read: 400 * 0.000001 * 0.5 = 0.0002
            // Total: 0.0008
            expectCostToBeCloseTo(result, 0.0008)
        })

        it('handles no provider field', () => {
            const event = createAIEvent({
                $ai_model: 'custom-model',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 400,
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
            const event = createAIEvent()
            const result = calculateInputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('returns 0 when input tokens is 0', () => {
            const event = createAIEvent({ $ai_input_tokens: 0 })

            const result = calculateInputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('handles undefined input tokens', () => {
            const event = createAIEvent({ $ai_model: 'test-model' })

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
            const event = createAIEvent({
                $ai_provider: 'anthropic',
                $ai_model: 'claude-3-5-sonnet',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: null as any,
                $ai_cache_creation_input_tokens: null as any,
            })

            const result = calculateInputCost(event, testModel)

            // Should treat null as 0
            expectCostToBeCloseTo(result, 0.001)
        })
    })

    describe('provider matching edge cases', () => {
        const testModel = createTestModel()

        it('handles undefined provider and model', () => {
            const event = createAIEvent({ $ai_input_tokens: 1000 })

            const result = calculateInputCost(event, testModel)

            // Should use default path
            expectCostToBeCloseTo(result, 0.001)
        })

        it('matches provider when only model contains provider name', () => {
            const event = createAIEvent({
                $ai_model: 'anthropic-claude-sonnet',
                $ai_input_tokens: 1000,
                $ai_cache_creation_input_tokens: 200,
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

            const event = createAIEvent({
                $ai_provider: 'custom',
                $ai_model: 'my-anthro-model',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 400,
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

            const event = createAIEvent({
                $ai_provider: 'gateway',
                $ai_model: 'ANTHROPIC/claude-sonnet',
                $ai_input_tokens: 1000,
                $ai_cache_creation_input_tokens: 200,
            })

            const result = calculateInputCost(event, anthropicModel)

            // Should match Anthropic path (case-insensitive)
            // Write: 200 * 0.00000375 = 0.00075
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00375
            expectCostToBeCloseTo(result, 0.00375)
        })

        it('matches Anthropic path for Claude models via Vertex provider', () => {
            // This tests the fix for negative costs when Claude models are accessed via Vertex
            // Vertex reports inputTokens excluding cache tokens (like Anthropic), not including them
            const event = createAIEvent({
                $ai_provider: 'vertex',
                $ai_model: 'claude-haiku-4-5',
                $ai_input_tokens: 457,
                $ai_cache_read_input_tokens: 36216,
            })

            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Should use Anthropic path because model starts with "claude"
            // Read: 36216 * 3e-7 = 0.0108648
            // Regular: 457 * 0.000003 = 0.001371
            // Total: 0.0122358
            expectCostToBeCloseTo(result, 0.0122358, 5)
        })

        it('matches Anthropic path for Claude models via Google provider', () => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'claude-3-5-sonnet',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 500,
            })

            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Should use Anthropic path because model starts with "claude"
            // Read: 500 * 3e-7 = 0.00015
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00315
            expectCostToBeCloseTo(result, 0.00315)
        })

        it('matches Anthropic path for Claude models with uppercase via non-Anthropic provider', () => {
            const event = createAIEvent({
                $ai_provider: 'bedrock',
                $ai_model: 'Claude-3-Opus',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 400,
            })

            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Should use Anthropic path (case-insensitive model check)
            // Read: 400 * 3e-7 = 0.00012
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00312
            expectCostToBeCloseTo(result, 0.00312)
        })
    })

    describe('explicit $ai_cache_reporting_exclusive flag', () => {
        it('uses exclusive accounting when flag is true on OpenAI event', () => {
            const event = createOpenAITestEvent(1000, 400, {
                $ai_cache_reporting_exclusive: true,
            })
            const result = calculateInputCost(event, OPENAI_MODEL)

            // Exclusive: no subtraction of cache tokens from input
            // Regular: 1000 * 0.0000025 = 0.0025
            // Read: 400 * 0.00000125 = 0.0005
            // Total: 0.003
            expectCostToBeCloseTo(result, 0.003)
        })

        it('uses inclusive accounting when flag is false on Anthropic event', () => {
            const event = createAnthropicTestEvent(1000, 500, undefined, {
                $ai_cache_reporting_exclusive: false,
            })
            const result = calculateInputCost(event, ANTHROPIC_MODEL)

            // Inclusive: subtracts cache tokens from input
            // Read: 500 * 3e-7 = 0.00015
            // Uncached: (1000 - 500) * 0.000003 = 0.0015
            // Total: 0.00015 + 0.0015 = 0.00165
            expectCostToBeCloseTo(result, 0.00165)
        })

        it('writes resolved value back to event properties', () => {
            const event = createAnthropicTestEvent(1000)
            calculateInputCost(event, ANTHROPIC_MODEL)
            expect(event.properties!['$ai_cache_reporting_exclusive']).toBe(true)
        })
    })

    describe('audio input - modality cost handling', () => {
        // gpt-4o-audio-preview pricing:
        // - text input: $2.50/1M ($0.0000025/token)
        // - audio input: $40/1M ($0.00004/token)
        const audioModel: ResolvedModelCost = {
            model: 'gpt-4o-audio-preview',
            provider: 'openai',
            cost: {
                prompt_token: 0.0000025,
                completion_token: 0.00001,
                audio: 0.00004,
            },
        }

        it('bills audio input tokens at the audio rate, not the prompt rate', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-4o-audio-preview',
                $ai_input_tokens: 1000, // 800 text + 200 audio
                $ai_audio_input_tokens: 200,
            })

            const result = calculateInputCost(event, audioModel)

            // Text: (1000 - 200) × 0.0000025 = 0.002
            // Audio: 200 × 0.00004 = 0.008
            // Total: 0.010
            expectCostToBeCloseTo(result, 0.01)
        })

        it('falls back to prompt rate when no audio rate is defined', () => {
            const modelWithoutAudioRate: ResolvedModelCost = {
                model: 'some-text-model',
                provider: 'openai',
                cost: { prompt_token: 0.000001, completion_token: 0.000002 },
            }
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'some-text-model',
                $ai_input_tokens: 1000,
                $ai_audio_input_tokens: 200,
            })

            const result = calculateInputCost(event, modelWithoutAudioRate)

            // Audio falls back to prompt rate, so total stays at 1000 × 0.000001 = 0.001
            expectCostToBeCloseTo(result, 0.001)
        })

        it('handles audio input combined with cache read tokens', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-4o-audio-preview',
                $ai_input_tokens: 1000, // 500 text + 200 audio + 300 cached (inclusive)
                $ai_cache_read_input_tokens: 300,
                $ai_audio_input_tokens: 200,
            })

            const result = calculateInputCost(event, {
                ...audioModel,
                cost: { ...audioModel.cost, cache_read_token: 0.00000125 },
            })

            // Text (uncached): (1000 - 300 - 200) × 0.0000025 = 0.00125
            // Cache read: 300 × 0.00000125 = 0.000375
            // Audio: 200 × 0.00004 = 0.008
            // Total: 0.00125 + 0.000375 + 0.008 = 0.009625
            expectCostToBeCloseTo(result, 0.009625)
        })
    })

    describe('image input - modality cost handling', () => {
        const imageInputModel: ResolvedModelCost = {
            model: 'gemini-2.5-flash',
            provider: 'google',
            cost: {
                prompt_token: 3e-7,
                completion_token: 0.0000025,
                image: 3e-7,
            },
        }

        it('bills image input tokens separately when image rate is defined', () => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-flash',
                $ai_input_tokens: 1000,
                $ai_image_input_tokens: 400,
            })

            const result = calculateInputCost(event, imageInputModel)

            // Text: (1000 - 400) × 3e-7 = 0.00018
            // Image: 400 × 3e-7 = 0.00012
            // Total: 0.0003
            expectCostToBeCloseTo(result, 0.0003)
        })

        it('clamps the text pool to zero when modality tokens exceed it', () => {
            // 500 input total, 400 cache read, 200 audio — the residual text pool
            // would be 500 - 400 - 200 = -100; clamp to 0 so we don't silently
            // understate the audio-billed cost via a negative text contribution.
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-4o-audio-preview',
                $ai_input_tokens: 500,
                $ai_cache_read_input_tokens: 400,
                $ai_audio_input_tokens: 200,
            })

            const result = calculateInputCost(event, {
                ...imageInputModel,
                model: 'gpt-4o-audio-preview',
                cost: {
                    prompt_token: 0.0000025,
                    completion_token: 0.00001,
                    cache_read_token: 0.00000125,
                    audio: 0.00004,
                },
            })

            // Text (clamped to 0): 0
            // Cache read: 400 × 0.00000125 = 0.0005
            // Audio: 200 × 0.00004 = 0.008
            // Total: 0.0085
            expectCostToBeCloseTo(result, 0.0085)
        })

        it('clamps the Anthropic uncached text pool to zero when modality tokens exceed it', () => {
            const event = createAIEvent({
                $ai_provider: 'anthropic',
                $ai_model: 'claude-3-5-sonnet',
                $ai_input_tokens: 100,
                $ai_image_input_tokens: 200, // exceeds inputTokens
            })
            const anthropicWithImage: ResolvedModelCost = {
                ...ANTHROPIC_MODEL,
                cost: { ...ANTHROPIC_MODEL.cost, image: 5e-7 },
            }

            const result = calculateInputCost(event, anthropicWithImage)

            // Anthropic exclusive: uncachedTokens = 100 - 200 = -100 (clamped to 0)
            // Image: 200 × 5e-7 = 0.0001
            // No cache costs
            // Total: 0.0001
            expectCostToBeCloseTo(result, 0.0001)
        })

        it('handles audio + image input together for multimodal calls', () => {
            const multiModalCost: ResolvedModelCost = {
                model: 'gemini-2.5-flash',
                provider: 'google',
                cost: {
                    prompt_token: 3e-7,
                    completion_token: 0.0000025,
                    image: 3e-7,
                    audio: 0.000001,
                },
            }
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-flash',
                $ai_input_tokens: 1000, // 400 text + 200 audio + 400 image
                $ai_audio_input_tokens: 200,
                $ai_image_input_tokens: 400,
            })

            const result = calculateInputCost(event, multiModalCost)

            // Text: 400 × 3e-7 = 0.00012
            // Audio: 200 × 0.000001 = 0.0002
            // Image: 400 × 3e-7 = 0.00012
            // Total: 0.00044
            expectCostToBeCloseTo(result, 0.00044)
        })
    })

    describe('cached audio input - cache modality cost handling', () => {
        // gpt-audio-mini pricing (representative — real numbers from llm-costs.json):
        // - text input: $0.15/1M
        // - text cache read: $0.075/1M
        // - audio input: $1.00/1M
        // - cached audio: $0.10/1M
        const audioCacheModel: ResolvedModelCost = {
            model: 'gpt-audio-mini',
            provider: 'openai',
            cost: {
                prompt_token: 0.00000015,
                completion_token: 0.0000006,
                cache_read_token: 0.000000075,
                audio: 0.000001,
                input_audio_cache: 0.0000001,
            },
        }

        it('bills cached audio at the cache rate and uncached audio at the audio rate', () => {
            // 1000 input total: 500 text uncached, 250 text cached, 50 audio cached, 150 audio uncached, 50 image
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-audio-mini',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 300, // 250 text + 50 audio
                $ai_audio_input_tokens: 200, // 150 uncached + 50 cached
                $ai_cache_read_audio_tokens: 50,
            })

            const result = calculateInputCost(event, audioCacheModel)

            // Cached text: 250 × 0.000000075 = 0.00001875
            // Uncached text: (1000 - 250 - 200) × 0.00000015 = 550 × 0.00000015 = 0.0000825
            // Uncached audio: 150 × 0.000001 = 0.00015
            // Cached audio: 50 × 0.0000001 = 0.000005
            // Total: 0.00001875 + 0.0000825 + 0.00015 + 0.000005 = 0.00025625
            expectCostToBeCloseTo(result, 0.00025625, 8)
        })

        it('falls back to text cache rate when input_audio_cache is undefined', () => {
            const modelWithoutAudioCacheRate: ResolvedModelCost = {
                model: 'mystery-audio-model',
                provider: 'openai',
                cost: {
                    prompt_token: 0.00000015,
                    completion_token: 0.0000006,
                    cache_read_token: 0.000000075,
                    audio: 0.000001,
                    // no input_audio_cache
                },
            }
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'mystery-audio-model',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 300,
                $ai_audio_input_tokens: 200,
                $ai_cache_read_audio_tokens: 50,
            })

            const result = calculateInputCost(event, modelWithoutAudioCacheRate)

            // Cached text: 250 × 0.000000075 = 0.00001875
            // Cached audio (falls back to text cache rate): 50 × 0.000000075 = 0.000003750
            // Uncached text: 550 × 0.00000015 = 0.0000825
            // Uncached audio: 150 × 0.000001 = 0.00015
            // Total: 0.00001875 + 0.00000375 + 0.0000825 + 0.00015 = 0.000255
            expectCostToBeCloseTo(result, 0.000255, 7)
        })

        it('falls back to prompt × 0.5 when no cache rate is configured at all', () => {
            const modelWithNoCacheRates: ResolvedModelCost = {
                model: 'no-cache-model',
                provider: 'openai',
                cost: {
                    prompt_token: 0.000001,
                    completion_token: 0.000002,
                    audio: 0.00004,
                    // no cache_read_token, no input_audio_cache
                },
            }
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'no-cache-model',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 300,
                $ai_audio_input_tokens: 200,
                $ai_cache_read_audio_tokens: 50,
            })

            const result = calculateInputCost(event, modelWithNoCacheRates)

            // Cached text (default 0.5 multiplier): 250 × 0.000001 × 0.5 = 0.000125
            // Cached audio (default 0.5 multiplier on prompt): 50 × 0.000001 × 0.5 = 0.000025
            // Uncached text: 550 × 0.000001 = 0.00055
            // Uncached audio: 150 × 0.00004 = 0.006
            // Total: 0.000125 + 0.000025 + 0.00055 + 0.006 = 0.0067
            expectCostToBeCloseTo(result, 0.0067, 6)
        })

        it('clamps cached_audio when it exceeds audio_input', () => {
            // Malformed event: cached_audio claims to be 300 but audio_input is only 100.
            // Bound it at 100 so we don't subtract more audio than we have.
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-audio-mini',
                $ai_input_tokens: 500,
                $ai_cache_read_input_tokens: 400,
                $ai_audio_input_tokens: 100,
                $ai_cache_read_audio_tokens: 300, // > audio_input
            })

            const result = calculateInputCost(event, audioCacheModel)

            // Effective cached_audio = min(300, 100, 400) = 100
            // Cached text: (400 - 100) × 0.000000075 = 300 × 0.000000075 = 0.0000225
            // Uncached text: (500 - 300 - 100) × 0.00000015 = 100 × 0.00000015 = 0.000015
            // Uncached audio: 0 × audio_rate = 0
            // Cached audio: 100 × 0.0000001 = 0.00001
            // Total: 0.0000225 + 0.000015 + 0.00001 = 0.0000475
            expectCostToBeCloseTo(result, 0.0000475, 8)
        })

        it('clamps cached_audio when it exceeds cache_read total', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-audio-mini',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 50, // smaller than claimed cached_audio
                $ai_audio_input_tokens: 200,
                $ai_cache_read_audio_tokens: 200, // > cache_read total
            })

            const result = calculateInputCost(event, audioCacheModel)

            // Effective cached_audio = min(200, 200, 50) = 50
            // Cached text: (50 - 50) × cache_rate = 0
            // Uncached text: (1000 - 0 - 200) × 0.00000015 = 800 × 0.00000015 = 0.00012
            // Uncached audio: (200 - 50) × 0.000001 = 0.00015
            // Cached audio: 50 × 0.0000001 = 0.000005
            // Total: 0.00012 + 0.00015 + 0.000005 = 0.000275
            expectCostToBeCloseTo(result, 0.000275, 7)
        })

        it('handles cached_audio = 0 (no-op)', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-audio-mini',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 300,
                $ai_audio_input_tokens: 200,
                $ai_cache_read_audio_tokens: 0,
            })

            const result = calculateInputCost(event, audioCacheModel)

            // Same as no $ai_cache_read_audio_tokens at all:
            // Cached text: 300 × 0.000000075 = 0.0000225
            // Uncached text: 500 × 0.00000015 = 0.000075
            // Audio: 200 × 0.000001 = 0.0002
            // Total: 0.0000225 + 0.000075 + 0.0002 = 0.0002975
            expectCostToBeCloseTo(result, 0.0002975, 7)
        })

        it('still works in Anthropic exclusive mode (cache and input pools are disjoint)', () => {
            // Hypothetical: Anthropic ever adds audio + cache. The exclusive flag
            // means cache_read is its own bucket, separate from input_tokens.
            const anthropicWithAudioCache: ResolvedModelCost = {
                model: 'claude-with-audio',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000003,
                    completion_token: 0.000015,
                    cache_read_token: 3e-7,
                    cache_write_token: 0.00000375,
                    audio: 0.000005,
                    input_audio_cache: 5e-7,
                },
            }
            const event = createAIEvent({
                $ai_provider: 'anthropic',
                $ai_model: 'claude-with-audio',
                $ai_input_tokens: 800, // text + audio (cache is separate in exclusive mode)
                $ai_cache_read_input_tokens: 200,
                $ai_audio_input_tokens: 100,
                $ai_cache_read_audio_tokens: 30,
            })

            const result = calculateInputCost(event, anthropicWithAudioCache)

            // Anthropic exclusive: input_tokens does NOT include cached.
            // Cached text: (200 - 30) × 3e-7 = 170 × 3e-7 = 0.000051
            // Uncached text: (800 - 100) × 0.000003 = 700 × 0.000003 = 0.0021
            // Uncached audio: (100 - 30) × 0.000005 = 70 × 0.000005 = 0.00035
            // Cached audio: 30 × 5e-7 = 0.000015
            // No cache_write tokens.
            // Total: 0.000051 + 0.0021 + 0.00035 + 0.000015 = 0.002516
            expectCostToBeCloseTo(result, 0.002516, 6)
        })

        it('clamps negative $ai_cache_read_audio_tokens to zero', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-audio-mini',
                $ai_input_tokens: 1000,
                $ai_cache_read_input_tokens: 300,
                $ai_audio_input_tokens: 200,
                $ai_cache_read_audio_tokens: -50, // malformed
            })

            const result = calculateInputCost(event, audioCacheModel)

            // Negative clamps to 0; result should match the no-cached-audio case.
            // Cached text: 300 × 0.000000075 = 0.0000225
            // Uncached text: 500 × 0.00000015 = 0.000075
            // Audio: 200 × 0.000001 = 0.0002
            // Total: 0.0002975
            expectCostToBeCloseTo(result, 0.0002975, 7)
        })

        it('handles cached audio together with cache_write tokens (Anthropic-style)', () => {
            const anthropicAudioCacheModel: ResolvedModelCost = {
                model: 'claude-with-audio',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000003,
                    completion_token: 0.000015,
                    cache_read_token: 3e-7,
                    cache_write_token: 0.00000375,
                    audio: 0.000005,
                    input_audio_cache: 5e-7,
                },
            }
            const event = createAIEvent({
                $ai_provider: 'anthropic',
                $ai_model: 'claude-with-audio',
                $ai_input_tokens: 800,
                $ai_cache_read_input_tokens: 200,
                $ai_cache_creation_input_tokens: 100, // cache write
                $ai_audio_input_tokens: 100,
                $ai_cache_read_audio_tokens: 30,
            })

            const result = calculateInputCost(event, anthropicAudioCacheModel)

            // Anthropic exclusive: input excludes both cache_read and cache_write.
            // Cache write: 100 × 0.00000375 = 0.000375
            // Cached text: (200 - 30) × 3e-7 = 0.000051
            // Uncached text: (800 - 100) × 0.000003 = 0.0021
            // Uncached audio: (100 - 30) × 0.000005 = 0.00035
            // Cached audio: 30 × 5e-7 = 0.000015
            // Total: 0.000375 + 0.000051 + 0.0021 + 0.00035 + 0.000015 = 0.002891
            expectCostToBeCloseTo(result, 0.002891, 6)
        })

        it('handles cached audio with Anthropic-via-Vercel inclusive reporting', () => {
            // Vercel AI Gateway flips Anthropic to inclusive cache reporting.
            // Same input pool semantics as OpenAI: input_tokens includes cached.
            const vercelAnthropicAudioModel: ResolvedModelCost = {
                model: 'claude-with-audio-vercel',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000003,
                    completion_token: 0.000015,
                    cache_read_token: 3e-7,
                    cache_write_token: 0.00000375,
                    audio: 0.000005,
                    input_audio_cache: 5e-7,
                },
            }
            const event = createAIEvent({
                $ai_provider: 'gateway',
                $ai_framework: 'vercel',
                $ai_model: 'anthropic/claude-with-audio',
                // Token totals consistent with inclusive reporting:
                // input_tokens already includes cache_read + cache_creation.
                $ai_input_tokens: 1100, // 800 text + 100 audio + 200 cache_read
                $ai_cache_read_input_tokens: 200,
                $ai_cache_creation_input_tokens: 0,
                $ai_audio_input_tokens: 100,
                $ai_cache_read_audio_tokens: 30,
            })

            const result = calculateInputCost(event, vercelAnthropicAudioModel)

            // Inclusive: input_tokens INCLUDES cache. So:
            //   uncached_text = input - cached_text - audio - image
            //                 = 1100 - (200 - 30) - 100 - 0 = 830
            // But wait, we also subtract cache_write_tokens=0. So uncached_text = 830.
            // Cache write: 0
            // Cached text: 170 × 3e-7 = 0.000051
            // Uncached text: 830 × 0.000003 = 0.00249
            // Uncached audio: 70 × 0.000005 = 0.00035
            // Cached audio: 30 × 5e-7 = 0.000015
            // Total: 0.000051 + 0.00249 + 0.00035 + 0.000015 = 0.002906
            expectCostToBeCloseTo(result, 0.002906, 6)
            // The auto-detector should have flipped cache reporting to inclusive
            // because the Vercel gateway sums input + cache.
            expect(event.properties!['$ai_cache_reporting_exclusive']).toBe(false)
        })
    })
})
