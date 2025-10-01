import { PluginEvent } from '@posthog/plugin-scaffold'

import { calculateOutputCost } from './output-costs'
import { ModelRow } from './providers/types'

describe('calculateOutputCost()', () => {
    describe('basic output cost calculation', () => {
        const basicModel: ModelRow = {
            model: 'gpt-4',
            provider: 'openai',
            cost: {
                prompt_token: 0.00003,
                completion_token: 0.00006,
            },
        }

        it('calculates output cost without reasoning tokens', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4',
                    $ai_output_tokens: 500,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, basicModel)

            // 500 * 0.00006 = 0.03
            expect(parseFloat(result)).toBeCloseTo(0.03, 6)
        })

        it('returns 0 when output tokens is 0', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4',
                    $ai_output_tokens: 0,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, basicModel)

            expect(result).toBe('0')
        })

        it('returns 0 when output tokens is undefined', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4',
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, basicModel)

            expect(result).toBe('0')
        })

        it('handles very large output token counts', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4',
                    $ai_output_tokens: 1e10,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, basicModel)

            expect(parseFloat(result)).toBeGreaterThan(0)
        })
    })

    describe('gemini 2.5 models - reasoning token handling', () => {
        const gemini25ProModel: ModelRow = {
            model: 'gemini-2.5-pro',
            provider: 'google',
            cost: {
                prompt_token: 0.00000125,
                completion_token: 0.00001,
            },
        }

        const gemini25FlashModel: ModelRow = {
            model: 'gemini-2.5-flash',
            provider: 'google',
            cost: {
                prompt_token: 3e-7,
                completion_token: 0.0000025,
            },
        }

        it('includes reasoning tokens for gemini-2.5-pro', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.5-pro',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini25ProModel)

            // (100 + 200) * 0.00001 = 300 * 0.00001 = 0.003
            expect(parseFloat(result)).toBeCloseTo(0.003, 6)
        })

        it('includes reasoning tokens for gemini-2.5-flash', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.5-flash',
                    $ai_output_tokens: 50,
                    $ai_reasoning_tokens: 150,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini25FlashModel)

            // (50 + 150) * 0.0000025 = 200 * 0.0000025 = 0.0005
            expect(parseFloat(result)).toBeCloseTo(0.0005, 6)
        })

        it('handles undefined reasoning tokens for gemini-2.5', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.5-pro',
                    $ai_output_tokens: 100,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini25ProModel)

            // (100 + 0) * 0.00001 = 0.001
            expect(parseFloat(result)).toBeCloseTo(0.001, 6)
        })

        it('handles zero reasoning tokens for gemini-2.5', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.5-flash',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 0,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini25FlashModel)

            // (100 + 0) * 0.0000025 = 0.00025
            expect(parseFloat(result)).toBeCloseTo(0.00025, 6)
        })

        it('is case-insensitive for model matching', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'GEMINI-2.5-PRO',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini25ProModel)

            // Should still include reasoning tokens
            expect(parseFloat(result)).toBeCloseTo(0.003, 6)
        })

        it('handles gemini-2.5 variants with suffixes', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.5-pro-preview-0514',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini25ProModel)

            // Should include reasoning tokens
            expect(parseFloat(result)).toBeCloseTo(0.003, 6)
        })

        it('handles very large reasoning token counts', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.5-pro',
                    $ai_output_tokens: 1000,
                    $ai_reasoning_tokens: 1e9,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini25ProModel)

            expect(parseFloat(result)).toBeGreaterThan(10000)
        })
    })

    describe('gemini 2.0 models - no reasoning token handling', () => {
        const gemini20FlashModel: ModelRow = {
            model: 'gemini-2.0-flash',
            provider: 'google',
            cost: {
                prompt_token: 1e-7,
                completion_token: 4e-7,
            },
        }

        it('does not include reasoning tokens for gemini-2.0', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.0-flash',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini20FlashModel)

            // Only output tokens, no reasoning: 100 * 4e-7 = 0.00004
            expect(parseFloat(result)).toBeCloseTo(0.00004, 7)
        })

        it('does not include reasoning tokens for gemini-2.0-flash-001', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.0-flash-001',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini20FlashModel)

            expect(parseFloat(result)).toBeCloseTo(0.00004, 7)
        })
    })

    describe('non-gemini models - no reasoning token handling', () => {
        const openaiModel: ModelRow = {
            model: 'gpt-4o',
            provider: 'openai',
            cost: {
                prompt_token: 0.0000025,
                completion_token: 0.00001,
            },
        }

        const anthropicModel: ModelRow = {
            model: 'claude-3-5-sonnet',
            provider: 'anthropic',
            cost: {
                prompt_token: 0.000003,
                completion_token: 0.000015,
            },
        }

        it('does not include reasoning tokens for OpenAI models', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'gpt-4o',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, openaiModel)

            // Only output tokens: 100 * 0.00001 = 0.001
            expect(parseFloat(result)).toBeCloseTo(0.001, 6)
        })

        it('does not include reasoning tokens for Anthropic models', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'anthropic',
                    $ai_model: 'claude-3-5-sonnet',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, anthropicModel)

            // Only output tokens: 100 * 0.000015 = 0.0015
            expect(parseFloat(result)).toBeCloseTo(0.0015, 6)
        })

        it('does not include reasoning tokens for o1 models', () => {
            const o1Model: ModelRow = {
                model: 'o1-mini',
                provider: 'openai',
                cost: {
                    prompt_token: 0.0000011,
                    completion_token: 0.0000044,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'openai',
                    $ai_model: 'o1-mini',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, o1Model)

            // Only output tokens: 100 * 0.0000044 = 0.00044
            expect(parseFloat(result)).toBeCloseTo(0.00044, 6)
        })

        it('does not include reasoning tokens for custom models', () => {
            const customModel: ModelRow = {
                model: 'custom-model',
                cost: {
                    prompt_token: 0.000001,
                    completion_token: 0.000002,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'custom',
                    $ai_model: 'custom-model',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, customModel)

            // Only output tokens: 100 * 0.000002 = 0.0002
            expect(parseFloat(result)).toBeCloseTo(0.0002, 6)
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

            const result = calculateOutputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('handles null output tokens', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_output_tokens: null as any,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('handles null reasoning tokens', () => {
            const gemini25Model: ModelRow = {
                model: 'gemini-2.5-pro',
                cost: {
                    prompt_token: 0.00000125,
                    completion_token: 0.00001,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_model: 'gemini-2.5-pro',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: null as any,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini25Model)

            // Should treat null as 0: 100 * 0.00001 = 0.001
            expect(parseFloat(result)).toBeCloseTo(0.001, 6)
        })

        it('handles negative output tokens', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_output_tokens: -100,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, testModel)

            // Should calculate even with negative (though invalid in practice)
            expect(parseFloat(result)).toBeLessThan(0)
        })

        it('handles negative reasoning tokens', () => {
            const gemini25Model: ModelRow = {
                model: 'gemini-2.5-pro',
                cost: {
                    prompt_token: 0.00000125,
                    completion_token: 0.00001,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_model: 'gemini-2.5-pro',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: -50,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini25Model)

            // (100 + (-50)) * 0.00001 = 50 * 0.00001 = 0.0005
            expect(parseFloat(result)).toBeCloseTo(0.0005, 6)
        })

        it('handles empty properties object', () => {
            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {},
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('handles missing model field for reasoning check', () => {
            const gemini25Model: ModelRow = {
                model: 'gemini-2.5-pro',
                cost: {
                    prompt_token: 0.00000125,
                    completion_token: 0.00001,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini25Model)

            // Without $ai_model, reasoning tokens won't be added (check is skipped when model is undefined)
            // Only output tokens: 100 * 0.00001 = 0.001
            expect(parseFloat(result)).toBeCloseTo(0.001, 6)
        })

        it('handles gemini-2.5 model variant names', () => {
            const gemini25FlashModel: ModelRow = {
                model: 'gemini-2.5-flash',
                cost: {
                    prompt_token: 3e-7,
                    completion_token: 0.0000025,
                },
            }

            const event: PluginEvent = {
                event: '$ai_generation',
                properties: {
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.5-flash-exp',
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }

            const result = calculateOutputCost(event, gemini25FlashModel)

            // Should include reasoning tokens: (100 + 200) * 0.0000025 = 0.00075
            expect(parseFloat(result)).toBeCloseTo(0.00075, 6)
        })
    })
})
