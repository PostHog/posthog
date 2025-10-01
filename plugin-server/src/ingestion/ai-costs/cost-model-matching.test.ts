import { Properties } from '@posthog/plugin-scaffold'

import { CostModelSource, findCostFromModel, getNewModelName, requireSpecialCost } from './cost-model-matching'

jest.mock('./providers', () => {
    const primaryCostsList = [
        {
            model: 'gpt-4',
            provider: 'openai',
            cost: { prompt_token: 0.00003, completion_token: 0.00006 },
        },
        {
            model: 'gpt-4o-mini',
            provider: 'openai',
            cost: { prompt_token: 0.00000015, completion_token: 0.0000006 },
        },
        {
            model: 'claude-3-5-sonnet',
            provider: 'anthropic',
            cost: {
                prompt_token: 0.000003,
                completion_token: 0.000015,
                cache_read_token: 3e-7,
                cache_write_token: 0.00000375,
            },
        },
        {
            model: 'gemini-2.5-pro',
            provider: 'google',
            cost: {
                prompt_token: 0.00000125,
                completion_token: 0.00001,
                cache_read_token: 3.1e-7,
            },
        },
    ]

    const backupCostsByModel = {
        'gpt-3.5-turbo': {
            model: 'gpt-3.5-turbo',
            cost: { prompt_token: 0.0000005, completion_token: 0.0000015 },
        },
        'claude-2': {
            model: 'claude-2',
            cost: { prompt_token: 0.000008, completion_token: 0.000024 },
        },
        'text-embedding-ada-002': {
            model: 'text-embedding-ada-002',
            cost: { prompt_token: 0.0000001, completion_token: 0 },
        },
        'mistral-7b-instruct-v0.2': {
            model: 'mistral-7b-instruct-v0.2',
            cost: { prompt_token: 0.0000002, completion_token: 0.0000002 },
        },
        'llama-3-70b-instruct': {
            model: 'llama-3-70b-instruct',
            cost: { prompt_token: 0.0000006, completion_token: 0.0000006 },
        },
    }

    return {
        primaryCostsList,
        backupCostsByModel,
    }
})

describe('findCostFromModel()', () => {
    describe('exact matching', () => {
        it('finds exact match in primary costs with provider', () => {
            const result = findCostFromModel('gpt-4', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('gpt-4')
            expect(result!.source).toBe(CostModelSource.Primary)
            expect(result!.cost.cost.prompt_token).toBe(0.00003)
        })

        it('finds exact match in backup costs without provider', () => {
            const result = findCostFromModel('gpt-3.5-turbo', {})

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('gpt-3.5-turbo')
            expect(result!.source).toBe(CostModelSource.Backup)
            expect(result!.cost.cost.prompt_token).toBe(0.0000005)
        })

        it('is case-insensitive for exact matches', () => {
            const result = findCostFromModel('GPT-4', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('gpt-4')
            expect(result!.source).toBe(CostModelSource.Primary)
        })

        it('matches with uppercase provider', () => {
            const result = findCostFromModel('claude-3-5-sonnet', { $ai_provider: 'ANTHROPIC' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('claude-3-5-sonnet')
            expect(result!.source).toBe(CostModelSource.Primary)
        })
    })

    describe('substring matching - known model in input model', () => {
        it('matches when known model is substring of input (gpt-4 in gpt-4-turbo)', () => {
            const result = findCostFromModel('gpt-4-turbo-2024-04-09', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('gpt-4')
            expect(result!.source).toBe(CostModelSource.Primary)
        })

        it('matches longest known model when multiple match', () => {
            const result = findCostFromModel('gpt-4o-mini-2024-07-18', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('gpt-4o-mini')
            expect(result!.source).toBe(CostModelSource.Primary)
        })

        it('matches claude variant in backup costs', () => {
            const result = findCostFromModel('claude-2.1', {})

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('claude-2')
            expect(result!.source).toBe(CostModelSource.Backup)
        })

        it('matches mistral variant', () => {
            const result = findCostFromModel('mistral-7b-instruct-v0.2-custom', {})

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('mistral-7b-instruct-v0.2')
            expect(result!.source).toBe(CostModelSource.Backup)
        })
    })

    describe('reverse substring matching - input model in known model', () => {
        it('matches when input is substring of known model', () => {
            const result = findCostFromModel('mistral-7b-instruct', {})

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('mistral-7b-instruct-v0.2')
            expect(result!.source).toBe(CostModelSource.Backup)
        })

        it('matches llama variant', () => {
            const result = findCostFromModel('llama-3', {})

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('llama-3-70b-instruct')
            expect(result!.source).toBe(CostModelSource.Backup)
        })
    })

    describe('provider filtering', () => {
        it('prefers primary costs when provider matches', () => {
            const result = findCostFromModel('gpt-4', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Primary)
            expect(result!.cost.provider).toBe('openai')
        })

        it('falls back to backup when provider does not match primary', () => {
            const result = findCostFromModel('gpt-3.5-turbo', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Backup)
        })

        it('uses backup costs when no provider specified', () => {
            const result = findCostFromModel('claude-2', {})

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Backup)
        })

        it('handles unknown provider gracefully', () => {
            const result = findCostFromModel('gpt-3.5-turbo', { $ai_provider: 'custom-provider' })

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Backup)
        })

        it('filters primary costs by provider correctly', () => {
            const resultOpenAI = findCostFromModel('gpt-4', { $ai_provider: 'openai' })
            const resultAnthropic = findCostFromModel('claude-3-5-sonnet', { $ai_provider: 'anthropic' })

            expect(resultOpenAI!.source).toBe(CostModelSource.Primary)
            expect(resultAnthropic!.source).toBe(CostModelSource.Primary)
        })
    })

    describe('gateway provider scenarios', () => {
        it('does not match models with provider prefix when using gateway', () => {
            const result = findCostFromModel('anthropic/claude-3-5-sonnet', { $ai_provider: 'gateway' })

            // Gateway provider will not match in primary costs, and "anthropic/claude-3-5-sonnet"
            // won't exactly match "claude-3-5-sonnet" in backup costs
            expect(result).toBeUndefined()
        })

        it('matches model without provider prefix', () => {
            const result = findCostFromModel('claude-3-5-sonnet', { $ai_provider: 'anthropic' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('claude-3-5-sonnet')
            expect(result!.source).toBe(CostModelSource.Primary)
        })
    })

    describe('edge cases', () => {
        it('returns undefined for completely unknown model', () => {
            const result = findCostFromModel('completely-unknown-model-xyz-123', { $ai_provider: 'unknown' })

            expect(result).toBeUndefined()
        })

        it('handles empty string model name', () => {
            const result = findCostFromModel('', { $ai_provider: 'openai' })

            // Empty string is technically a substring of all models, so it matches the first one
            // This is likely unintended behavior but is how the current implementation works
            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Primary)
        })

        it('handles model name with special characters', () => {
            const result = findCostFromModel('gpt-4@latest', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('gpt-4')
        })

        it('handles model name with slashes', () => {
            const result = findCostFromModel('models/gpt-4', { $ai_provider: 'openai' })

            expect(result).toBeDefined()
            expect(result!.cost.model).toBe('gpt-4')
        })

        it('handles undefined properties', () => {
            const result = findCostFromModel('gpt-3.5-turbo', undefined)

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Backup)
        })

        it('handles properties without provider field', () => {
            const result = findCostFromModel('claude-2', { $ai_model: 'claude-2' })

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Backup)
        })

        it('handles null provider', () => {
            const result = findCostFromModel('gpt-3.5-turbo', { $ai_provider: null as any })

            expect(result).toBeDefined()
            expect(result!.source).toBe(CostModelSource.Backup)
        })
    })

    describe('cost data completeness', () => {
        it('returns model with cache costs when available', () => {
            const result = findCostFromModel('claude-3-5-sonnet', { $ai_provider: 'anthropic' })

            expect(result).toBeDefined()
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
    describe('gemini-2.5-pro-preview threshold logic', () => {
        it('returns standard model name for input tokens <= 200k', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
                $ai_input_tokens: 200000,
            }

            expect(getNewModelName(properties)).toBe('gemini-2.5-pro-preview')
        })

        it('returns large model name for input tokens > 200k', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
                $ai_input_tokens: 200001,
            }

            expect(getNewModelName(properties)).toBe('gemini-2.5-pro-preview:large')
        })

        it('handles significantly large input tokens', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
                $ai_input_tokens: 1000000,
            }

            expect(getNewModelName(properties)).toBe('gemini-2.5-pro-preview:large')
        })

        it('returns standard model when input tokens is undefined', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
            }

            expect(getNewModelName(properties)).toBe('gemini-2.5-pro-preview')
        })

        it('returns standard model when input tokens is 0', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
                $ai_input_tokens: 0,
            }

            expect(getNewModelName(properties)).toBe('gemini-2.5-pro-preview')
        })

        it('is case-insensitive for model name', () => {
            const properties: Properties = {
                $ai_model: 'GEMINI-2.5-PRO-PREVIEW',
                $ai_input_tokens: 250000,
            }

            expect(getNewModelName(properties)).toBe('gemini-2.5-pro-preview:large')
        })

        it('works with model variants containing gemini-2.5-pro-preview', () => {
            const properties: Properties = {
                $ai_model: 'google/gemini-2.5-pro-preview-0514',
                $ai_input_tokens: 250000,
            }

            expect(getNewModelName(properties)).toBe('gemini-2.5-pro-preview:large')
        })
    })

    describe('non-special models', () => {
        it('returns original model name for gpt-4', () => {
            const properties: Properties = {
                $ai_model: 'gpt-4',
                $ai_input_tokens: 300000,
            }

            expect(getNewModelName(properties)).toBe('gpt-4')
        })

        it('returns original model name for claude models', () => {
            const properties: Properties = {
                $ai_model: 'claude-3-5-sonnet',
                $ai_input_tokens: 300000,
            }

            expect(getNewModelName(properties)).toBe('claude-3-5-sonnet')
        })

        it('returns original model name for other gemini models', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.0-flash',
                $ai_input_tokens: 300000,
            }

            expect(getNewModelName(properties)).toBe('gemini-2.0-flash')
        })
    })

    describe('edge cases', () => {
        it('handles undefined model', () => {
            const properties: Properties = {
                $ai_input_tokens: 250000,
            }

            expect(getNewModelName(properties)).toBeUndefined()
        })

        it('handles null model', () => {
            const properties: Properties = {
                $ai_model: null as any,
                $ai_input_tokens: 250000,
            }

            expect(getNewModelName(properties)).toBeNull()
        })

        it('handles empty string model', () => {
            const properties: Properties = {
                $ai_model: '',
                $ai_input_tokens: 250000,
            }

            expect(getNewModelName(properties)).toBe('')
        })

        it('handles negative input tokens', () => {
            const properties: Properties = {
                $ai_model: 'gemini-2.5-pro-preview',
                $ai_input_tokens: -1000,
            }

            expect(getNewModelName(properties)).toBe('gemini-2.5-pro-preview')
        })
    })
})
