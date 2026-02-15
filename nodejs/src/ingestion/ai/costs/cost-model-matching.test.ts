import { Properties } from '@posthog/plugin-scaffold'

import { CostModelSource, findCostFromModel, getNewModelName, requireSpecialCost } from './cost-model-matching'

jest.mock('./providers', () => {
    const openRouterCostsByModel = {
        'openai/gpt-4': {
            model: 'openai/gpt-4',
            cost: {
                default: { prompt_token: 0.00004, completion_token: 0.00008 },
                openai: { prompt_token: 0.00003, completion_token: 0.00006 },
            },
        },
        'openai/gpt-4o-mini': {
            model: 'openai/gpt-4o-mini',
            cost: {
                default: { prompt_token: 0.0000002, completion_token: 0.0000007 },
                openai: { prompt_token: 0.00000015, completion_token: 0.0000006 },
            },
        },
        'anthropic/claude-3.5-sonnet': {
            model: 'anthropic/claude-3.5-sonnet',
            cost: {
                default: {
                    prompt_token: 0.000004,
                    completion_token: 0.000018,
                },
                anthropic: {
                    prompt_token: 0.000003,
                    completion_token: 0.000015,
                    cache_read_token: 3e-7,
                    cache_write_token: 0.00000375,
                },
            },
        },
        'google/gemini-2.5-pro-preview': {
            model: 'google/gemini-2.5-pro-preview',
            cost: {
                default: {
                    prompt_token: 0.0000015,
                    completion_token: 0.000012,
                },
                'google-ai-studio': {
                    prompt_token: 0.00000125,
                    completion_token: 0.00001,
                    cache_read_token: 3.1e-7,
                },
            },
        },
    }

    const manualCostsByModel = {
        'gpt-3.5-turbo': {
            model: 'gpt-3.5-turbo',
            cost: {
                default: { prompt_token: 0.0000005, completion_token: 0.0000015 },
                openai: { prompt_token: 0.0000005, completion_token: 0.0000015 },
            },
        },
        'claude-2': {
            model: 'claude-2',
            cost: {
                default: { prompt_token: 0.000008, completion_token: 0.000024 },
                anthropic: { prompt_token: 0.000008, completion_token: 0.000024 },
            },
        },
        'claude-3-5-sonnet': {
            model: 'claude-3-5-sonnet',
            cost: {
                default: {
                    prompt_token: 0.000003,
                    completion_token: 0.000015,
                    cache_read_token: 3e-7,
                    cache_write_token: 0.00000375,
                },
            },
        },
        'text-embedding-ada-002': {
            model: 'text-embedding-ada-002',
            cost: {
                default: { prompt_token: 0.0000001, completion_token: 0 },
            },
        },
        'mistral-7b-instruct-v0.2': {
            model: 'mistral-7b-instruct-v0.2',
            cost: {
                default: { prompt_token: 0.0000002, completion_token: 0.0000002 },
                mistral: { prompt_token: 0.0000002, completion_token: 0.0000002 },
            },
        },
        'llama-3-70b-instruct': {
            model: 'llama-3-70b-instruct',
            cost: {
                default: { prompt_token: 0.0000006, completion_token: 0.0000006 },
            },
        },
    }

    return {
        openRouterCostsByModel,
        manualCostsByModel,
    }
})

describe('findCostFromModel()', () => {
    describe('exact matching', () => {
        it('finds exact match in primary costs with provider', () => {
            const result = findCostFromModel('gpt-4', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('openai/gpt-4')
            expect(result!.source).toBe(CostModelSource.OpenRouter)
            expect(result!.cost.cost.prompt_token).toBe(0.00003)
        })

        it('finds exact match in manual costs without provider', () => {
            const result = findCostFromModel('gpt-3.5-turbo', {})

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('gpt-3.5-turbo')
            expect(result!.source).toBe(CostModelSource.Manual)
            expect(result!.cost.cost.prompt_token).toBe(0.0000005)
        })

        it('finds manual cost when model has provider prefix', () => {
            const result = findCostFromModel('openai/gpt-3.5-turbo', {})

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('gpt-3.5-turbo')
            expect(result!.source).toBe(CostModelSource.Manual)
            expect(result!.cost.cost.prompt_token).toBe(0.0000005)
        })

        it('finds manual cost with provider prefix and provider property', () => {
            const result = findCostFromModel('anthropic/claude-2', { $ai_provider: 'openrouter' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('claude-2')
            expect(result!.source).toBe(CostModelSource.Manual)
            expect(result!.cost.cost.prompt_token).toBe(0.000008)
        })

        it('is case-insensitive for exact matches', () => {
            const result = findCostFromModel('GPT-4', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('openai/gpt-4')
            expect(result!.source).toBe(CostModelSource.OpenRouter)
        })

        it('matches with uppercase provider', () => {
            const result = findCostFromModel('claude-3-5-sonnet', { $ai_provider: 'ANTHROPIC' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('claude-3-5-sonnet')
            expect(result!.source).toBe(CostModelSource.Manual)
        })

        it('prefers manual costs over primary costs when both exist', () => {
            const result = findCostFromModel('claude-3-5-sonnet', { $ai_provider: 'anthropic' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('claude-3-5-sonnet')
            expect(result!.source).toBe(CostModelSource.Manual)
        })
    })

    describe('substring matching - known model in input model', () => {
        it('matches when known model is substring of input (gpt-4 in gpt-4-turbo)', () => {
            const result = findCostFromModel('gpt-4-turbo-2024-04-09', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('openai/gpt-4')
            expect(result!.source).toBe(CostModelSource.OpenRouter)
        })

        it('matches longest known model when multiple match', () => {
            const result = findCostFromModel('gpt-4o-mini-2024-07-18', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('openai/gpt-4o-mini')
            expect(result!.source).toBe(CostModelSource.OpenRouter)
        })

        it('matches anthropic claude variants when punctuation differs', () => {
            const result = findCostFromModel('claude-3-5-sonnet-20241022', { $ai_provider: 'anthropic' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('anthropic/claude-3.5-sonnet')
            expect(result!.cost.provider).toBe('anthropic')
            expect(result!.source).toBe(CostModelSource.OpenRouter)
        })

        it('does not match manual costs by substring', () => {
            const result = findCostFromModel('claude-2.1', {})

            expect(result).toBeUndefined()
        })

        it('requires exact manual match when input extends known model name', () => {
            const result = findCostFromModel('mistral-7b-instruct-v0.2-custom', {})

            expect(result).toBeUndefined()
        })
    })

    describe('manual reverse substring matching is disabled', () => {
        it('does not match when input is substring of manual model name', () => {
            const result = findCostFromModel('mistral-7b-instruct', {})

            expect(result).toBeUndefined()
        })

        it('does not match llama variant without exact manual name', () => {
            const result = findCostFromModel('llama-3', {})

            expect(result).toBeUndefined()
        })
    })

    describe('provider filtering', () => {
        it('prefers primary costs when provider matches', () => {
            const result = findCostFromModel('gpt-4', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.OpenRouter)
            expect(result!.cost.provider).toBe('openai')
        })

        it('returns manual costs when provider does not match primary', () => {
            const result = findCostFromModel('gpt-3.5-turbo', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Manual)
        })

        it('uses manual costs when no provider specified', () => {
            const result = findCostFromModel('claude-2', {})

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Manual)
        })

        it('handles unknown provider by returning manual costs', () => {
            const result = findCostFromModel('gpt-3.5-turbo', { $ai_provider: 'custom-provider' })

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Manual)
        })

        it('filters primary costs by provider correctly', () => {
            const resultOpenAI = findCostFromModel('gpt-4', { $ai_provider: 'openai' })
            const resultAnthropic = findCostFromModel('claude-3-5-sonnet', { $ai_provider: 'anthropic' })

            expect(resultOpenAI!.source).toBe(CostModelSource.OpenRouter)
            expect(resultOpenAI!.cost.model).toBe('openai/gpt-4')
            expect(resultAnthropic!.source).toBe(CostModelSource.Manual)
            expect(resultAnthropic!.cost.provider).toBe('default')
        })
    })

    describe('gateway provider scenarios', () => {
        it('finds manual cost when model has provider prefix, even with gateway provider', () => {
            const result = findCostFromModel('anthropic/claude-3-5-sonnet', { $ai_provider: 'gateway' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('claude-3-5-sonnet')
            expect(result!.cost.provider).toBe('default')
            expect(result!.source).toBe(CostModelSource.Manual)
        })

        it('falls back to OpenRouter when no manual cost exists for prefixed model', () => {
            const result = findCostFromModel('openai/gpt-4', { $ai_provider: 'gateway' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('openai/gpt-4')
            expect(result!.cost.provider).toBe('default')
            expect(result!.source).toBe(CostModelSource.OpenRouter)
        })

        it('matches model without provider prefix', () => {
            const result = findCostFromModel('claude-3-5-sonnet', { $ai_provider: 'anthropic' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('claude-3-5-sonnet')
            expect(result!.source).toBe(CostModelSource.Manual)
            expect(result!.cost.provider).toBe('default')
        })
    })

    describe('edge cases', () => {
        it('returns undefined for completely unknown model', () => {
            const result = findCostFromModel('completely-unknown-model-xyz-123', { $ai_provider: 'unknown' })

            expect(result).toBeUndefined()
        })

        it('handles empty string model name', () => {
            const result = findCostFromModel('', { $ai_provider: 'openai' })

            expect(result).toBeUndefined()
        })

        it('handles model name with special characters', () => {
            const result = findCostFromModel('gpt-4@latest', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('openai/gpt-4')
        })

        it('handles model name with slashes', () => {
            const result = findCostFromModel('models/gpt-4', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('openai/gpt-4')
        })

        it('throws when properties object is undefined', () => {
            expect(() => findCostFromModel('gpt-3.5-turbo', undefined as unknown as Properties)).toThrow(TypeError)
        })

        it('handles properties without provider field', () => {
            const result = findCostFromModel('claude-2', { $ai_model: 'claude-2' })

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Manual)
        })

        it('handles null provider', () => {
            const result = findCostFromModel('gpt-3.5-turbo', { $ai_provider: null as any })

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Manual)
        })
    })

    describe('cost data completeness', () => {
        it('returns model with cache costs when available', () => {
            const result = findCostFromModel('claude-3-5-sonnet', { $ai_provider: 'anthropic' })

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Manual)
            expect(result!.cost.cost.cache_read_token).toBe(3e-7)
            expect(result!.cost.cost.cache_write_token).toBe(0.00000375)
        })

        it('returns model without cache costs for models that do not support it', () => {
            const result = findCostFromModel('gpt-3.5-turbo', {})

            expect(result).toBeDefined()
            expect(result!.cost.cost.cache_read_token).toBeUndefined()
            expect(result!.cost.cost.cache_write_token).toBeUndefined()
        })

        it('returns embedding model with zero completion cost', () => {
            const result = findCostFromModel('text-embedding-ada-002', {})

            expect(result).toBeDefined()
            expect(result!.cost.cost.completion_token).toBe(0)
        })
    })
})

describe('requireSpecialCost()', () => {
    it('returns true for gemini-2.5-pro-preview', () => {
        expect(requireSpecialCost('gemini-2.5-pro-preview')).toBe(true)
    })

    it('returns true for gemini-2.5-pro-preview variants', () => {
        expect(requireSpecialCost('gemini-2.5-pro-preview-0514')).toBe(true)
    })

    it('is case-insensitive', () => {
        expect(requireSpecialCost('GEMINI-2.5-PRO-PREVIEW')).toBe(true)
        expect(requireSpecialCost('Gemini-2.5-Pro-Preview')).toBe(true)
    })

    it('returns false for other gemini models', () => {
        expect(requireSpecialCost('gemini-2.0-flash')).toBe(false)
        expect(requireSpecialCost('gemini-1.5-pro')).toBe(false)
    })

    it('returns false for non-gemini models', () => {
        expect(requireSpecialCost('gpt-4')).toBe(false)
        expect(requireSpecialCost('claude-3-5-sonnet')).toBe(false)
    })

    it('returns false for empty string', () => {
        expect(requireSpecialCost('')).toBe(false)
    })
})

describe('getNewModelName()', () => {
    const callGetNewModelName = (properties: Properties) =>
        getNewModelName(properties.$ai_model as string, properties.$ai_input_tokens)

    describe('gemini-2.5-pro-preview threshold logic', () => {
        it('returns standard model name for input tokens <= 200k', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
                $ai_input_tokens: 200000,
            }

            expect(callGetNewModelName(properties)).toBe('gemini-2.5-pro-preview')
        })

        it('returns large model name for input tokens > 200k', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
                $ai_input_tokens: 200001,
            }

            expect(callGetNewModelName(properties)).toBe('gemini-2.5-pro-preview:large')
        })

        it('handles significantly large input tokens', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
                $ai_input_tokens: 1000000,
            }

            expect(callGetNewModelName(properties)).toBe('gemini-2.5-pro-preview:large')
        })

        it('returns standard model when input tokens is undefined', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
            }

            expect(callGetNewModelName(properties)).toBe('gemini-2.5-pro-preview')
        })

        it('returns standard model when input tokens is 0', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
                $ai_input_tokens: 0,
            }

            expect(callGetNewModelName(properties)).toBe('gemini-2.5-pro-preview')
        })

        it('is case-insensitive for model name', () => {
            const properties: Properties = {
                $ai_model: 'GEMINI-2.5-PRO-PREVIEW',
                $ai_input_tokens: 250000,
            }

            expect(callGetNewModelName(properties)).toBe('gemini-2.5-pro-preview:large')
        })

        it('works with model variants containing gemini-2.5-pro-preview', () => {
            const properties: Properties = {
                $ai_model: 'google/gemini-2.5-pro-preview-0514',
                $ai_input_tokens: 250000,
            }

            expect(callGetNewModelName(properties)).toBe('gemini-2.5-pro-preview:large')
        })
    })

    describe('non-special models', () => {
        it('returns original model name for gpt-4', () => {
            const properties: Properties = {
                $ai_model: 'gpt-4',
                $ai_input_tokens: 300000,
            }

            expect(callGetNewModelName(properties)).toBe('gpt-4')
        })

        it('returns original model name for claude models', () => {
            const properties: Properties = {
                $ai_model: 'claude-3-5-sonnet',
                $ai_input_tokens: 300000,
            }

            expect(callGetNewModelName(properties)).toBe('claude-3-5-sonnet')
        })

        it('returns original model name for other gemini models', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.0-flash',
                $ai_input_tokens: 300000,
            }

            expect(callGetNewModelName(properties)).toBe('gemini-2.0-flash')
        })
    })

    describe('edge cases', () => {
        it('handles empty string model', () => {
            const properties: Properties = {
                $ai_model: '',
                $ai_input_tokens: 250000,
            }

            expect(callGetNewModelName(properties)).toBe('')
        })

        it('handles negative input tokens', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
                $ai_input_tokens: -1000,
            }

            expect(callGetNewModelName(properties)).toBe('gemini-2.5-pro-preview')
        })
    })
})
