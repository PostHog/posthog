import { PluginEvent } from '@posthog/plugin-scaffold'

import { calculateInputCost } from './input-costs'
import { ModelRow } from './providers/types'

describe('calculateInputCost()', () => {
    describe('anthropic provider - cache handling', () => {
        const anthropicModel: ModelRow = {
            model: 'claude-3-5-sonnet',
            provider: 'anthropic',
            cost: {
                prompt_token: 0.000003,
                completion_token: 0.000015,
                cache_read_token: 3e-7,
                cache_write_token: 0.00000375,
            },
        }

        it('calculates cost with cache read tokens using explicit costs', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'anthropic',
                    $ai_model: 'claude-3-5-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 500,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, anthropicModel)

            // Read: 500 * 3e-7 = 0.00015
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00015 + 0.003 = 0.00315
            expect(parseFloat(result)).toBeCloseTo(0.00315, 6)
        })

        it('calculates cost with cache write tokens using explicit costs', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'anthropic',
                    $ai_model: 'claude-3-5-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_creation_input_tokens: 300,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, anthropicModel)

            // Write: 300 * 0.00000375 = 0.001125
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.001125 + 0.003 = 0.004125
            expect(parseFloat(result)).toBeCloseTo(0.004125, 6)
        })

        it('calculates cost with both read and write cache tokens', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'anthropic',
                    $ai_model: 'claude-3-5-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 500,
                    $ai_cache_creation_input_tokens: 300,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, anthropicModel)

            // Write: 300 * 0.00000375 = 0.001125
            // Read: 500 * 3e-7 = 0.00015
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.001125 + 0.00015 + 0.003 = 0.004275
            expect(parseFloat(result)).toBeCloseTo(0.004275, 6)
        })

        it('uses 1.25x multiplier fallback for cache write when not defined', () => {
            const modelWithoutCacheWrite: ModelRow = {
                model: 'claude-2',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000008,
                    completion_token: 0.000024,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'anthropic',
                    $ai_model: 'claude-2',
                    $ai_input_tokens: 1000,
                    $ai_cache_creation_input_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, modelWithoutCacheWrite)

            // Write: 200 * 0.000008 * 1.25 = 0.002
            // Regular: 1000 * 0.000008 = 0.008
            // Total: 0.002 + 0.008 = 0.01
            expect(parseFloat(result)).toBeCloseTo(0.01, 6)
        })

        it('uses 0.1x multiplier fallback for cache read when not defined', () => {
            const modelWithoutCacheRead: ModelRow = {
                model: 'claude-2',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000008,
                    completion_token: 0.000024,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'anthropic',
                    $ai_model: 'claude-2',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 400,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, modelWithoutCacheRead)

            // Read: 400 * 0.000008 * 0.1 = 0.00032
            // Regular: 1000 * 0.000008 = 0.008
            // Total: 0.00032 + 0.008 = 0.00832
            expect(parseFloat(result)).toBeCloseTo(0.00832, 6)
        })

        it('handles zero cache tokens correctly', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'anthropic',
                    $ai_model: 'claude-3-5-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 0,
                    $ai_cache_creation_input_tokens: 0,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, anthropicModel)

            // Regular: 1000 * 0.000003 = 0.003
            expect(parseFloat(result)).toBeCloseTo(0.003, 6)
        })

        it('handles undefined cache tokens correctly', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'anthropic',
                    $ai_model: 'claude-3-5-sonnet',
                    $ai_input_tokens: 1000,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, anthropicModel)

            // Regular: 1000 * 0.000003 = 0.003
            expect(parseFloat(result)).toBeCloseTo(0.003, 6)
        })

        it('matches provider case-insensitively', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'ANTHROPIC',
                    $ai_model: 'claude-3-5-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 500,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, anthropicModel)

            // Should still use Anthropic path
            // Read: 500 * 3e-7 = 0.00015
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00315
            expect(parseFloat(result)).toBeCloseTo(0.00315, 6)
        })

        it('matches provider in model string', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'gateway',
                    $ai_model: 'anthropic/claude-3-5-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_creation_input_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, anthropicModel)

            // Should use Anthropic path because model contains "anthropic"
            // Write: 200 * 0.00000375 = 0.00075
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00375
            expect(parseFloat(result)).toBeCloseTo(0.00375, 6)
        })
    })

    describe('openai provider - cache handling', () => {
        const openaiModel: ModelRow = {
            model: 'gpt-4o',
            provider: 'openai',
            cost: {
                prompt_token: 0.0000025,
                completion_token: 0.00001,
                cache_read_token: 0.00000125,
            },
        }

        it('calculates cost with cache read tokens using explicit costs', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4o',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 400,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, openaiModel)

            // Regular: (1000 - 400) * 0.0000025 = 600 * 0.0000025 = 0.0015
            // Read: 400 * 0.00000125 = 0.0005
            // Total: 0.0015 + 0.0005 = 0.002
            expect(parseFloat(result)).toBeCloseTo(0.002, 6)
        })

        it('uses 0.5x multiplier fallback when cache_read_token not defined', () => {
            const modelWithoutCacheRead: ModelRow = {
                model: 'gpt-4',
                provider: 'openai',
                cost: {
                    prompt_token: 0.00003,
                    completion_token: 0.00006,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 400,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, modelWithoutCacheRead)

            // Regular: (1000 - 400) * 0.00003 = 600 * 0.00003 = 0.018
            // Read: 400 * 0.00003 * 0.5 = 0.006
            // Total: 0.018 + 0.006 = 0.024
            expect(parseFloat(result)).toBeCloseTo(0.024, 6)
        })

        it('handles zero cache read tokens', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4o',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 0,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, openaiModel)

            // Regular: 1000 * 0.0000025 = 0.0025
            expect(parseFloat(result)).toBeCloseTo(0.0025, 6)
        })

        it('handles undefined cache read tokens', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4o',
                    $ai_input_tokens: 1000,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, openaiModel)

            // Regular: 1000 * 0.0000025 = 0.0025
            expect(parseFloat(result)).toBeCloseTo(0.0025, 6)
        })

        it('matches provider in model string for gateway', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'gateway',
                    $ai_model: 'openai/gpt-4o',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 400,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, openaiModel)

            // Should use OpenAI/default path (not Anthropic)
            // Regular: (1000 - 400) * 0.0000025 = 0.0015
            // Read: 400 * 0.00000125 = 0.0005
            // Total: 0.002
            expect(parseFloat(result)).toBeCloseTo(0.002, 6)
        })
    })

    describe('gemini provider - cache handling', () => {
        const geminiModel: ModelRow = {
            model: 'gemini-2.5-pro',
            provider: 'google',
            cost: {
                prompt_token: 0.00000125,
                completion_token: 0.00001,
                cache_read_token: 3.1e-7,
            },
        }

        it('calculates cost with cache read tokens using explicit costs', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.5-pro',
                    $ai_input_tokens: 10000,
                    $ai_cache_read_input_tokens: 4000,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, geminiModel)

            // Regular: (10000 - 4000) * 0.00000125 = 6000 * 0.00000125 = 0.0075
            // Read: 4000 * 3.1e-7 = 0.00124
            // Total: 0.0075 + 0.00124 = 0.00874
            expect(parseFloat(result)).toBeCloseTo(0.00874, 6)
        })

        it('handles zero cache read tokens', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.5-pro',
                    $ai_input_tokens: 10000,
                    $ai_cache_read_input_tokens: 0,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, geminiModel)

            // Regular: 10000 * 0.00000125 = 0.0125
            expect(parseFloat(result)).toBeCloseTo(0.0125, 6)
        })
    })

    describe('default provider - cache handling', () => {
        const customModel: ModelRow = {
            model: 'custom-model',
            cost: {
                prompt_token: 0.000001,
                completion_token: 0.000002,
            },
        }

        it('uses 0.5x multiplier for cache read when provider unknown', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'custom-provider',
                    $ai_model: 'custom-model',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 400,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, customModel)

            // Regular: (1000 - 400) * 0.000001 = 0.0006
            // Read: 400 * 0.000001 * 0.5 = 0.0002
            // Total: 0.0008
            expect(parseFloat(result)).toBeCloseTo(0.0008, 6)
        })

        it('handles no provider field', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_model: 'custom-model',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 400,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, customModel)

            // Should use default path
            // Regular: (1000 - 400) * 0.000001 = 0.0006
            // Read: 400 * 0.000001 * 0.5 = 0.0002
            // Total: 0.0008
            expect(parseFloat(result)).toBeCloseTo(0.0008, 6)
        })
    })

    describe('edge cases', () => {
        const testModel: ModelRow = {
            model: 'test-model',
            cost: {
                prompt_token: 0.000001,
                completion_token: 0.000002,
            },
        }

        it('returns 0 when properties is undefined', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('returns 0 when input tokens is 0', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_input_tokens: 0,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('handles undefined input tokens', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_model: 'test-model',
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('handles cache read tokens exceeding input tokens', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4',
                    $ai_input_tokens: 100,
                    $ai_cache_read_input_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, testModel)

            // Regular: (100 - 200) = -100, negative regular tokens
            // Read: 200 * 0.000001 * 0.5 = 0.0001
            // Regular: -100 * 0.000001 = -0.0001
            // Total: 0.0001 + (-0.0001) = 0
            expect(parseFloat(result)).toBeCloseTo(0, 6)
        })

        it('handles very large token counts', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4',
                    $ai_input_tokens: 1e10,
                    $ai_cache_read_input_tokens: 5e9,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, testModel)

            expect(parseFloat(result)).toBeGreaterThan(0)
        })

        it('handles negative token counts gracefully', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4',
                    $ai_input_tokens: -1000,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, testModel)

            // Should calculate even with negative (though invalid in practice)
            expect(parseFloat(result)).toBeLessThan(0)
        })

        it('handles null cache token values', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'anthropic',
                    $ai_model: 'claude-3-5-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: null as any,
                    $ai_cache_creation_input_tokens: null as any,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, testModel)

            // Should treat null as 0
            expect(parseFloat(result)).toBeCloseTo(0.001, 6)
        })
    })

    describe('provider matching edge cases', () => {
        const testModel: ModelRow = {
            model: 'test-model',
            cost: {
                prompt_token: 0.000001,
                completion_token: 0.000002,
            },
        }

        it('handles undefined provider and model', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_input_tokens: 1000,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, testModel)

            // Should use default path
            expect(parseFloat(result)).toBeCloseTo(0.001, 6)
        })

        it('matches provider when only model contains provider name', () => {
            const anthropicModel: ModelRow = {
                model: 'claude-3-5-sonnet',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000003,
                    completion_token: 0.000015,
                    cache_read_token: 3e-7,
                    cache_write_token: 0.00000375,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_model: 'anthropic-claude-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_creation_input_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, anthropicModel)

            // Should use Anthropic path because "anthropic" is in model
            // Write: 200 * 0.00000375 = 0.00075
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00375
            expect(parseFloat(result)).toBeCloseTo(0.00375, 6)
        })

        it('does not match partial provider names', () => {
            const anthropicModel: ModelRow = {
                model: 'claude-3-5-sonnet',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000003,
                    completion_token: 0.000015,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'custom',
                    $ai_model: 'my-anthro-model',
                    $ai_input_tokens: 1000,
                    $ai_cache_read_input_tokens: 400,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, anthropicModel)

            // Should NOT match Anthropic because "anthro" != "anthropic"
            // Uses default path: (1000-400) * 0.000003 + 400 * 0.000003 * 0.5
            expect(parseFloat(result)).toBeCloseTo(0.0024, 6)
        })

        it('is case-insensitive for provider matching in model string', () => {
            const anthropicModel: ModelRow = {
                model: 'claude-3-5-sonnet',
                provider: 'anthropic',
                cost: {
                    prompt_token: 0.000003,
                    completion_token: 0.000015,
                    cache_write_token: 0.00000375,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'gateway',
                    $ai_model: 'ANTHROPIC/claude-sonnet',
                    $ai_input_tokens: 1000,
                    $ai_cache_creation_input_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateInputCost(event, anthropicModel)

            // Should match Anthropic path (case-insensitive)
            // Write: 200 * 0.00000375 = 0.00075
            // Regular: 1000 * 0.000003 = 0.003
            // Total: 0.00375
            expect(parseFloat(result)).toBeCloseTo(0.00375, 6)
        })
    })
})
