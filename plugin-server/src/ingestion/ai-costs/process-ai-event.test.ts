import { PluginEvent } from '@posthog/plugin-scaffold'

import { logger } from '../../utils/logger'
import { CostModelSource } from './cost-model-matching'
import { normalizeTraceProperties, processAiEvent } from './process-ai-event'

jest.mock('../../utils/logger', () => ({
    logger: {
        warn: jest.fn(),
    },
}))

const mockWarn = logger.warn as jest.Mock

const costsByModel = {
    testing_model: { model: 'testing_model', cost: { prompt_token: 0.1, completion_token: 0.1 } },
    'gpt-4': { model: 'gpt-4', cost: { prompt_token: 0.2, completion_token: 0.2 } },
    'gpt-4-0125-preview': { model: 'gpt-4-0125-preview', cost: { prompt_token: 0.3, completion_token: 0.3 } },
    'mistral-7b-instruct-v0.1': {
        model: 'mistral-7b-instruct-v0.1',
        cost: { prompt_token: 0.4, completion_token: 0.4 },
    },
    'gpt-4o-mini': { model: 'gpt-4o-mini', cost: { prompt_token: 0.5, completion_token: 0.5 } },
    'claude-2': { model: 'claude-2', cost: { prompt_token: 0.6, completion_token: 0.6 } },
    'claude-sonnet-4': {
        model: 'claude-sonnet-4',
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000015,
            cache_read_token: 3e-7,
            cache_write_token: 0.00000375,
        },
    },
    'gemini-2.5-pro-preview': {
        model: 'gemini-2.5-pro-preview',
        cost: { prompt_token: 0.00000125, completion_token: 0.00001, cache_read_token: 3.1e-7 },
    },
    'gemini-2.5-pro-preview:large': {
        model: 'gemini-2.5-pro-preview:large',
        cost: { prompt_token: 0.0000025, completion_token: 0.000015, cache_read_token: 0.000000625 },
    },
    'gemini-2.5-flash': {
        model: 'gemini-2.5-flash',
        cost: { prompt_token: 3e-7, completion_token: 0.0000025, cache_read_token: 7.5e-8 },
    },
    'gemini-2.0-flash-001': {
        model: 'gemini-2.0-flash-001',
        cost: { prompt_token: 1e-7, completion_token: 4e-7, cache_read_token: 2.5e-8 },
    },
    'o1-mini': {
        model: 'o1-mini',
        cost: { prompt_token: 0.0000011, completion_token: 0.0000044 },
    },
    'gpt-4.1': { model: 'gpt-4.1', cost: { prompt_token: 0.9, completion_token: 0.9 } },
}

jest.mock('./providers', () => {
    const originalProviders = jest.requireActual('./providers')

    const mockBackupCostsByModel = {
        testing_model: { model: 'testing_model', cost: { prompt_token: 0.1, completion_token: 0.1 } },
        'gpt-4': { model: 'gpt-4', cost: { prompt_token: 0.2, completion_token: 0.2 } },
        'gpt-4-0125-preview': { model: 'gpt-4-0125-preview', cost: { prompt_token: 0.3, completion_token: 0.3 } },
        'mistral-7b-instruct-v0.1': {
            model: 'mistral-7b-instruct-v0.1',
            cost: { prompt_token: 0.4, completion_token: 0.4 },
        },
        'gpt-4o-mini': { model: 'gpt-4o-mini', cost: { prompt_token: 0.5, completion_token: 0.5 } },
        'claude-2': { model: 'claude-2', cost: { prompt_token: 0.6, completion_token: 0.6 } },
        'claude-sonnet-4': {
            model: 'claude-sonnet-4',
            cost: {
                prompt_token: 0.000003,
                completion_token: 0.000015,
                cache_read_token: 3e-7,
                cache_write_token: 0.00000375,
            },
        },
        'gemini-2.5-pro-preview': {
            model: 'gemini-2.5-pro-preview',
            cost: { prompt_token: 0.00000125, completion_token: 0.00001, cache_read_token: 3.1e-7 },
        },
        'gemini-2.5-pro-preview:large': {
            model: 'gemini-2.5-pro-preview:large',
            cost: { prompt_token: 0.0000025, completion_token: 0.000015, cache_read_token: 0.000000625 },
        },
        'gemini-2.5-flash': {
            model: 'gemini-2.5-flash',
            cost: { prompt_token: 3e-7, completion_token: 0.0000025, cache_read_token: 7.5e-8 },
        },
        'gemini-2.0-flash-001': {
            model: 'gemini-2.0-flash-001',
            cost: { prompt_token: 1e-7, completion_token: 4e-7, cache_read_token: 2.5e-8 },
        },
        'o1-mini': {
            model: 'o1-mini',
            cost: { prompt_token: 0.0000011, completion_token: 0.0000044 },
        },
        'gpt-4.1': { model: 'gpt-4.1', cost: { prompt_token: 0.9, completion_token: 0.9 } },
        'backup-model': { model: 'backup-model', cost: { prompt_token: 0.5, completion_token: 0.5 } },
        'fallback-model': { model: 'fallback-model', cost: { prompt_token: 0.6, completion_token: 0.6 } },
    }

    return {
        ...originalProviders,
        primaryCostsList: [
            { model: 'openai-primary', provider: 'openai', cost: { prompt_token: 0.7, completion_token: 0.7 } },
            { model: 'anthropic-primary', provider: 'anthropic', cost: { prompt_token: 0.8, completion_token: 0.8 } },
            { model: 'gpt-4', provider: 'openai', cost: { prompt_token: 0.2, completion_token: 0.2 } },
        ],
        backupCostsByModel: mockBackupCostsByModel,
    }
})

describe('processAiEvent()', () => {
    let event: PluginEvent

    beforeEach(() => {
        jest.clearAllMocks()
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
        it.each(['$ai_generation', '$ai_embedding'])('processes cost calculation for %s events', (eventType) => {
            event.event = eventType
            const result = processAiEvent(event)
            // With gpt-4 model and openai provider from primaryCostsList: 0.2 per token
            expect(result.properties!.$ai_input_cost_usd).toBe(20) // 100 * 0.2
            expect(result.properties!.$ai_output_cost_usd).toBe(10) // 50 * 0.2
            expect(result.properties!.$ai_total_cost_usd).toBe(30)
        })

        it('does not process cost for other AI events', () => {
            event.event = '$ai_span'
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBeUndefined()
        })

        it('does not match non-AI events', () => {
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

        it('extracts anthropic-specific parameters', () => {
            event.properties!.$ai_provider = 'anthropic'
            event.properties!.$ai_model_parameters = {
                temperature: 0.7,
                max_tokens: 200,
                stream: true,
                some_other_param: 'ignored',
            }
            const result = processAiEvent(event)
            expect(result.properties!.$ai_temperature).toBe(0.7)
            expect(result.properties!.$ai_max_tokens).toBe(200)
            expect(result.properties!.$ai_stream).toBe(true)
        })

        it('extracts parameters for unknown providers using openai defaults', () => {
            event.properties!.$ai_provider = 'custom-provider'
            event.properties!.$ai_model_parameters = {
                temperature: 0.8,
                max_completion_tokens: 300,
                stream: false,
            }
            const result = processAiEvent(event)
            expect(result.properties!.$ai_temperature).toBe(0.8)
            expect(result.properties!.$ai_max_tokens).toBe(300)
            expect(result.properties!.$ai_stream).toBe(false)
        })

        it('handles missing provider gracefully', () => {
            delete event.properties!.$ai_provider
            event.properties!.$ai_model_parameters = {
                temperature: 0.5,
            }
            const result = processAiEvent(event)
            // Extracts parameters even without provider
            expect(result.properties!.$ai_temperature).toBe(0.5)
        })

        it('handles empty model parameters object', () => {
            event.properties!.$ai_model_parameters = {}
            const result = processAiEvent(event)
            expect(result.properties!.$ai_temperature).toBeUndefined()
            expect(result.properties!.$ai_max_tokens).toBeUndefined()
            expect(result.properties!.$ai_stream).toBeUndefined()
        })

        it('preserves undefined parameter values', () => {
            event.properties!.$ai_model_parameters = {
                temperature: undefined,
                max_completion_tokens: undefined,
                stream: undefined,
            }
            const result = processAiEvent(event)
            expect(result.properties!.$ai_temperature).toBeUndefined()
            expect(result.properties!.$ai_max_tokens).toBeUndefined()
            expect(result.properties!.$ai_stream).toBeUndefined()
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

        it('handles null properties object', () => {
            event.properties = null as any
            const result = processAiEvent(event)
            expect(result.properties).toBeNull()
        })

        it('handles events without properties', () => {
            delete (event as any).properties
            const result = processAiEvent(event)
            expect(result.properties).toBeUndefined()
        })
    })

    describe('provider-specific cost filtering', () => {
        it('uses primary costs when provider matches', () => {
            event.properties!.$ai_provider = 'openai'
            event.properties!.$ai_model = 'openai-primary'
            const result = processAiEvent(event)

            // Should use openai-primary from primaryCostsList (0.7 per token)
            expect(result.properties!.$ai_model_cost_used).toBe('openai-primary')
            expect(result.properties!.$ai_cost_model_source).toBe(CostModelSource.Primary)
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(70, 2)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(35, 2)
        })

        it('falls back to backup costs when primary not found', () => {
            event.properties!.$ai_provider = 'custom'
            event.properties!.$ai_model = 'fallback-model'
            const result = processAiEvent(event)

            // Should use fallback-model from backupCostsByModel
            expect(result.properties!.$ai_model_cost_used).toBe('fallback-model')
            expect(result.properties!.$ai_cost_model_source).toBe(CostModelSource.Backup)
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(60, 2)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(30, 2)
        })

        it('logs warning when no cost found', () => {
            event.properties!.$ai_provider = 'unknown'
            event.properties!.$ai_model = 'completely-unknown-model-xyz-123'

            processAiEvent(event)

            expect(mockWarn).toHaveBeenCalledWith(
                expect.stringContaining('No cost found for model: completely-unknown-model-xyz-123')
            )
        })
    })

    describe('model cost tracking', () => {
        it('sets $ai_model_cost_used to track which model was used for cost calculation', () => {
            event.properties!.$ai_model = 'gpt-4-turbo-0125-preview'
            const result = processAiEvent(event)

            // Based on the matching logic, with provider=openai, it would match gpt-4 first from primaryCostsList
            expect(result.properties!.$ai_model_cost_used).toBe('gpt-4')
            expect(result.properties!.$ai_cost_model_source).toBe(CostModelSource.Primary)
        })

        it('tracks exact model match', () => {
            event.properties!.$ai_model = 'claude-2'
            const result = processAiEvent(event)

            expect(result.properties!.$ai_model_cost_used).toBe('claude-2')
            expect(result.properties!.$ai_cost_model_source).toBe(CostModelSource.Backup)
        })

        it('does not set model_cost_used when no match found', () => {
            event.properties!.$ai_model = 'unknown-model-xyz'
            const result = processAiEvent(event)

            expect(result.properties!.$ai_model_cost_used).toBeUndefined()
            expect(result.properties!.$ai_cost_model_source).toBeUndefined()
        })

        it('uses backup costs when model is only in backup', () => {
            event.properties!.$ai_model = 'backup-model'
            const result = processAiEvent(event)

            expect(result.properties!.$ai_model_cost_used).toBe('backup-model')
            expect(result.properties!.$ai_cost_model_source).toBe(CostModelSource.Backup)
        })

        it('uses primary costs when anthropic provider matches anthropic-primary', () => {
            event.properties!.$ai_provider = 'anthropic'
            event.properties!.$ai_model = 'anthropic-primary'
            const result = processAiEvent(event)

            expect(result.properties!.$ai_model_cost_used).toBe('anthropic-primary')
            expect(result.properties!.$ai_cost_model_source).toBe(CostModelSource.Primary)
        })
    })

    describe('cost optimization bypass', () => {
        it('skips calculation when costs are pre-calculated', () => {
            event.properties!.$ai_input_cost_usd = 10.5
            event.properties!.$ai_output_cost_usd = 5.5
            const result = processAiEvent(event)

            // Should not recalculate, should keep existing values
            expect(result.properties!.$ai_input_cost_usd).toBe(10.5)
            expect(result.properties!.$ai_output_cost_usd).toBe(5.5)
            expect(result.properties!.$ai_total_cost_usd).toBe(16)
            // Should not set model_cost_used when bypassing
            expect(result.properties!.$ai_model_cost_used).toBeUndefined()
        })

        it('calculates total when input/output exist but total is missing', () => {
            event.properties!.$ai_input_cost_usd = 3.5
            event.properties!.$ai_output_cost_usd = 2.5
            delete event.properties!.$ai_total_cost_usd

            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBe(6)
        })

        it('preserves existing total cost when all costs are present', () => {
            event.properties!.$ai_input_cost_usd = 3
            event.properties!.$ai_output_cost_usd = 2
            event.properties!.$ai_total_cost_usd = 10 // Intentionally different

            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBe(10)
        })
    })

    describe('custom token pricing', () => {
        it('uses custom pricing when provided', () => {
            event.properties!.$ai_input_token_price = 0.001
            event.properties!.$ai_output_token_price = 0.002
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.1, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.1, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.2, 6)
            expect(result.properties!.$ai_model_cost_used).toBe('custom')
            expect(result.properties!.$ai_cost_model_source).toBe(CostModelSource.Custom)
        })

        it('uses custom pricing even when model is unknown', () => {
            event.properties!.$ai_model = 'completely-unknown-model'
            event.properties!.$ai_input_token_price = 0.0005
            event.properties!.$ai_output_token_price = 0.0015
            event.properties!.$ai_input_tokens = 200
            event.properties!.$ai_output_tokens = 100

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.1, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.15, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.25, 6)
            expect(result.properties!.$ai_model_cost_used).toBe('custom')
        })

        it('custom pricing takes precedence over model matching', () => {
            event.properties!.$ai_model = 'gpt-4'
            event.properties!.$ai_provider = 'openai'
            event.properties!.$ai_input_token_price = 0.1
            event.properties!.$ai_output_token_price = 0.2
            event.properties!.$ai_input_tokens = 10
            event.properties!.$ai_output_tokens = 5

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(1, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(1, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(2, 6)
            expect(result.properties!.$ai_model_cost_used).toBe('custom')
        })

        it('pre-calculated costs take precedence over custom pricing', () => {
            event.properties!.$ai_input_cost_usd = 5.5
            event.properties!.$ai_output_cost_usd = 3.5
            event.properties!.$ai_input_token_price = 0.001
            event.properties!.$ai_output_token_price = 0.002
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBe(5.5)
            expect(result.properties!.$ai_output_cost_usd).toBe(3.5)
            expect(result.properties!.$ai_total_cost_usd).toBe(9)
            expect(result.properties!.$ai_model_cost_used).toBeUndefined()
        })

        it('handles custom pricing with cache read tokens for OpenAI', () => {
            event.properties!.$ai_provider = 'openai'
            event.properties!.$ai_input_token_price = 0.001
            event.properties!.$ai_output_token_price = 0.002
            event.properties!.$ai_cache_read_token_price = 0.0005
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_cache_read_input_tokens = 40
            event.properties!.$ai_output_tokens = 50

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.08, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.1, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.18, 6)
        })

        it('handles custom pricing with cache tokens for Anthropic', () => {
            event.properties!.$ai_provider = 'anthropic'
            event.properties!.$ai_input_token_price = 0.000003
            event.properties!.$ai_output_token_price = 0.000015
            event.properties!.$ai_cache_read_token_price = 0.0000003
            event.properties!.$ai_cache_write_token_price = 0.00000375
            event.properties!.$ai_input_tokens = 1000
            event.properties!.$ai_cache_read_input_tokens = 500
            event.properties!.$ai_cache_creation_input_tokens = 200
            event.properties!.$ai_output_tokens = 100

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.0039, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.0015, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.0054, 6)
        })

        it('falls back to multipliers when cache prices not provided', () => {
            event.properties!.$ai_provider = 'openai'
            event.properties!.$ai_input_token_price = 0.001
            event.properties!.$ai_output_token_price = 0.002
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_cache_read_input_tokens = 40
            event.properties!.$ai_output_tokens = 50

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.08, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.1, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.18, 6)
        })

        it('handles zero custom prices', () => {
            event.properties!.$ai_input_token_price = 0
            event.properties!.$ai_output_token_price = 0
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBe(0)
            expect(result.properties!.$ai_output_cost_usd).toBe(0)
            expect(result.properties!.$ai_total_cost_usd).toBe(0)
            expect(result.properties!.$ai_model_cost_used).toBe('custom')
        })

        it('requires both input and output prices to use custom pricing', () => {
            event.properties!.$ai_input_token_price = 0.001
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50

            const result = processAiEvent(event)

            expect(result.properties!.$ai_model_cost_used).toBe('gpt-4')
            expect(result.properties!.$ai_cost_model_source).toBe(CostModelSource.Primary)
        })

        it('works without provider when using custom pricing', () => {
            delete event.properties!.$ai_provider
            event.properties!.$ai_input_token_price = 0.001
            event.properties!.$ai_output_token_price = 0.002
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.1, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.1, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.2, 6)
        })

        it('works without model when using custom pricing', () => {
            delete event.properties!.$ai_model
            event.properties!.$ai_input_token_price = 0.001
            event.properties!.$ai_output_token_price = 0.002
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.1, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.1, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.2, 6)
        })

        it('handles reasoning tokens with custom pricing for gemini-2.5 models', () => {
            event.properties!.$ai_provider = 'google'
            event.properties!.$ai_model = 'gemini-2.5-flash'
            event.properties!.$ai_input_token_price = 0.0000003
            event.properties!.$ai_output_token_price = 0.0000025
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50
            event.properties!.$ai_reasoning_tokens = 200

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.00003, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.000625, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.000655, 6)
        })
    })

    describe('model name edge cases', () => {
        it('handles empty string model names', () => {
            event.properties!.$ai_model = ''
            const result = processAiEvent(event)
            expect(result.properties!.$ai_total_cost_usd).toBeUndefined()
        })

        it('handles case-insensitive model matching', () => {
            event.properties!.$ai_model = 'GPT-4' // Uppercase
            const result = processAiEvent(event)
            expect(result.properties!.$ai_model_cost_used).toBe('gpt-4')
            expect(result.properties!.$ai_total_cost_usd).toBeDefined()
        })

        it('handles model names with special characters using substring matching', () => {
            // Test various special character scenarios in a single test
            const specialCases = [
                { model: 'gpt-4-日本語', expected: 'gpt-4' },
                { model: 'gpt-4@latest#v2', expected: 'gpt-4' },
                { model: 'openai/gpt-4', expected: 'gpt-4' },
            ]

            for (const { model, expected } of specialCases) {
                event.properties!.$ai_model = model
                const result = processAiEvent(event)
                expect(result.properties!.$ai_model_cost_used).toBe(expected)
            }
        })
    })

    describe('edge cases in token handling', () => {
        it('handles very large token numbers', () => {
            event.properties!.$ai_input_tokens = 1e10
            event.properties!.$ai_output_tokens = 1e10

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBeGreaterThan(0)
            expect(result.properties!.$ai_output_cost_usd).toBeGreaterThan(0)
            expect(result.properties!.$ai_total_cost_usd).toBeGreaterThan(0)
        })

        it('handles scientific notation in token counts', () => {
            event.properties!.$ai_input_tokens = 1.5e3 // 1500
            event.properties!.$ai_output_tokens = 2e2 // 200

            const result = processAiEvent(event)

            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(300, 2) // 1500 * 0.2
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(40, 2) // 200 * 0.2
        })
    })

    describe('model cost calculations', () => {
        it.each([
            { model: 'testing_model', inputCost: 10, outputCost: 5, totalCost: 15 },
            { model: 'gpt-4', inputCost: 20, outputCost: 10, totalCost: 30 },
            { model: 'gpt-4o-mini', inputCost: 50, outputCost: 25, totalCost: 75 },
            { model: 'claude-2', inputCost: 60, outputCost: 30, totalCost: 90 },
            { model: 'o1-mini', inputCost: 0.00011, outputCost: 0.00022, totalCost: 0.00033 },
        ])('calculates correct costs for $model', ({ model, inputCost, outputCost, totalCost }) => {
            event.properties!.$ai_model = model
            event.properties!.$ai_provider = undefined // Use backup costs
            const result = processAiEvent(event)
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(inputCost, 2)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(outputCost, 2)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(totalCost, 2)
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

    describe('cache costs with defined values', () => {
        it('uses actual cache costs when defined in model', () => {
            event.properties!.$ai_provider = 'anthropic'
            event.properties!.$ai_model = 'claude-sonnet-4' // Has defined cache costs
            event.properties!.$ai_input_tokens = 1000
            event.properties!.$ai_output_tokens = 100
            event.properties!.$ai_cache_read_input_tokens = 500
            event.properties!.$ai_cache_creation_input_tokens = 200

            const result = processAiEvent(event)

            // claude-sonnet-4: prompt=0.000003, cache_read=3e-7, cache_write=0.00000375
            // Write: 200 * 0.00000375 = 0.00075
            // Read: 500 * 3e-7 = 0.00015
            // Regular: 1000 * 0.000003 = 0.003
            // Total input: 0.00075 + 0.00015 + 0.003 = 0.0039
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.0039, 6)

            // Output: 100 * 0.000015 = 0.0015
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.0015, 6)
        })

        it('falls back to multipliers when cache costs not defined', () => {
            event.properties!.$ai_provider = 'anthropic'
            event.properties!.$ai_model = 'testing_model' // No defined cache costs
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_cache_read_input_tokens = 50
            event.properties!.$ai_cache_creation_input_tokens = 20

            const result = processAiEvent(event)

            // testing_model: prompt=0.1, no cache costs defined
            // Write: 20 * 0.1 * 1.25 = 2.5
            // Read: 50 * 0.1 * 0.1 = 0.5
            // Regular: 100 * 0.1 = 10
            // Total input: 2.5 + 0.5 + 10 = 13
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(13, 2)
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

    describe('gateway provider handling', () => {
        it('handles Anthropic models through gateway provider with cache tokens', () => {
            // Simulate the exact user scenario
            event.properties!.$ai_provider = 'gateway'
            event.properties!.$ai_model = 'anthropic/claude-sonnet-4'
            event.properties!.$ai_input_tokens = 3815
            event.properties!.$ai_output_tokens = 460
            event.properties!.$ai_cache_creation_input_tokens = 84329

            const result = processAiEvent(event)

            // Should use claude-sonnet-4 costs from manual providers
            expect(result.properties!.$ai_model_cost_used).toBe('claude-sonnet-4')

            // Cache creation: 84329 * 0.000003 * 1.25 = 0.31623375
            // Regular input: 3815 * 0.000003 = 0.011445
            // Total input: 0.31623375 + 0.011445 = 0.32767875
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.327679, 5)

            // Output: 460 * 0.000015 = 0.0069
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.0069, 4)

            // Total: 0.327679 + 0.0069 = 0.334579
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.334579, 5)
        })

        it('handles OpenAI models through gateway provider', () => {
            event.properties!.$ai_provider = 'gateway'
            event.properties!.$ai_model = 'openai/gpt-4'
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50
            event.properties!.$ai_cache_read_input_tokens = 40

            const result = processAiEvent(event)

            expect(result.properties!.$ai_model_cost_used).toBe('gpt-4')
            // Should calculate OpenAI cache costs correctly
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(16, 2) // (40*0.2*0.5) + (60*0.2) = 4 + 12 = 16
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(10, 2) // 50 * 0.2 = 10
        })

        it('matches provider when provider name appears anywhere in model string', () => {
            event.properties!.$ai_provider = 'gateway'
            event.properties!.$ai_model = 'some-prefix-anthropic-claude-sonnet-4'
            event.properties!.$ai_input_tokens = 3815
            event.properties!.$ai_output_tokens = 460
            event.properties!.$ai_cache_creation_input_tokens = 84329

            const result = processAiEvent(event)

            expect(result.properties!.$ai_model_cost_used).toBe('claude-sonnet-4')

            // Cache creation: 84329 * 0.000003 * 1.25 = 0.31623375
            // Regular input: 3815 * 0.000003 = 0.011445
            // Total input: 0.31623375 + 0.011445 = 0.32767875
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.327679, 5)

            // Output: 460 * 0.000015 = 0.0069
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.0069, 4)

            // Total: 0.327679 + 0.0069 = 0.334579
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.334579, 5)
        })
    })

    describe('gemini 2.5 pro preview', () => {
        it('handles missing model property in getNewModelName', () => {
            const eventWithoutModel = {
                ...event,
                properties: {
                    ...event.properties,
                    $ai_model: undefined,
                    $ai_input_tokens: 250000,
                },
            }

            const result = processAiEvent(eventWithoutModel)
            expect(result.properties!.$ai_total_cost_usd).toBeUndefined()
        })

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

            // With provider=openai, it matches gpt-4 from primaryCostsList first
            const expectedInputCost = inputTokens * 0.2 // 100 * 0.2
            const expectedOutputCost = outputTokens * 0.2 // 50 * 0.2

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

        it('matches gpt-4 from primary costs when provider is openai (not gpt-4.1 from backup)', () => {
            // This test verifies that primary costs are preferred over backup costs
            // even when backup has a longer matching model name
            event.properties!.$ai_model = 'gpt-4.1-preview-0502'
            const result = processAiEvent(event)

            // With provider=openai, it matches gpt-4 from primaryCostsList (0.2 per token)
            // rather than gpt-4.1 from backup (0.9 per token)
            expect(result.properties!.$ai_model_cost_used).toBe('gpt-4')
            expect(result.properties!.$ai_input_cost_usd).toBe(20) // 100 * 0.2
            expect(result.properties!.$ai_output_cost_usd).toBe(10) // 50 * 0.2
            expect(result.properties!.$ai_total_cost_usd).toBe(30)
        })

        it('returns undefined costs if no matching rule applies after all checks', () => {
            event.properties!.$ai_model = 'completely_unknown_model_structure_123_xyz_very_unique'
            const result = processAiEvent(event)
            expect(result.properties!.$ai_input_cost_usd).toBeUndefined()
            expect(result.properties!.$ai_output_cost_usd).toBeUndefined()
            expect(result.properties!.$ai_total_cost_usd).toBeUndefined()
        })
    })

    describe('reasoning token handling', () => {
        it('includes reasoning tokens for gemini-2.5-*', () => {
            event.properties!.$ai_provider = 'google'
            event.properties!.$ai_model = 'gemini-2.5-flash'
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50
            event.properties!.$ai_reasoning_tokens = 200

            const result = processAiEvent(event)

            // For gemini-2.5-flash: prompt_token = 3e-7, completion_token = 0.0000025
            // Input cost: 100 * 3e-7 = 0.00003
            // Output cost: (50 + 200) * 0.0000025 = 250 * 0.0000025 = 0.000625
            // Total cost: 0.00003 + 0.000625 = 0.000655
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.00003, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.000625, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.000655, 6)
        })

        it('handles undefined reasoning tokens for gemini-2.5-*', () => {
            event.properties!.$ai_provider = 'google'
            event.properties!.$ai_model = 'gemini-2.5-flash'
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50
            // $ai_reasoning_tokens is intentionally undefined

            const result = processAiEvent(event)

            // For gemini-2.5-flash: prompt_token = 3e-7, completion_token = 0.0000025
            // Input cost: 100 * 3e-7 = 0.00003
            // Output cost: (50 + 0) * 0.0000025 = 50 * 0.0000025 = 0.000125 (undefined reasoning tokens treated as 0)
            // Total cost: 0.00003 + 0.000125 = 0.000155
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.00003, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.000125, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.000155, 6)
        })

        it('does not include reasoning tokens for gemini-2.0-*', () => {
            event.properties!.$ai_provider = 'google'
            event.properties!.$ai_model = 'gemini-2.0-flash'
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50
            event.properties!.$ai_reasoning_tokens = 200

            const result = processAiEvent(event)

            // Model will match gemini-2.0-flash-001: prompt_token = 1e-7, completion_token = 4e-7
            // Input cost: 100 * 1e-7 = 0.00001
            // Output cost: 50 * 4e-7 = 0.00002 (reasoning tokens ignored)
            // Total cost: 0.00001 + 0.00002 = 0.00003
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.00001, 7)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.00002, 7)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.00003, 7)
        })

        it('does not include reasoning tokens for non gemini models', () => {
            event.properties!.$ai_provider = 'openai'
            event.properties!.$ai_model = 'o1-mini'
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_output_tokens = 50
            event.properties!.$ai_reasoning_tokens = 200

            const result = processAiEvent(event)

            // For o1-mini: prompt_token = 0.0000011, completion_token = 0.0000044
            // Input cost: 100 * 0.0000011 = 0.00011
            // Output cost: 50 * 0.0000044 = 0.00022 (reasoning tokens ignored)
            // Total cost: 0.00011 + 0.00022 = 0.00033
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.00011, 5)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.00022, 5)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.00033, 5)
        })
    })

    describe('gemini cache handling', () => {
        it('handles cache read tokens with correct cost calculation for gemini-2.5-pro-preview', () => {
            event.properties!.$ai_provider = 'gemini'
            event.properties!.$ai_model = 'gemini-2.5-pro-preview'
            event.properties!.$ai_input_tokens = 1000
            event.properties!.$ai_cache_read_input_tokens = 400
            event.properties!.$ai_output_tokens = 50

            const result = processAiEvent(event)

            // Regular tokens: 1000 - 400 = 600
            // Input cost: (600 * 0.00000125) + (400 * 3.1e-7) = 0.00075 + 0.000124 = 0.000874
            // Output cost: 50 * 0.00001 = 0.0005
            // Total cost: 0.000874 + 0.0005 = 0.001374
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.000874, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.0005, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.001374, 6)
        })

        it('handles cache read tokens for gemini-2.5-pro-preview:large', () => {
            event.properties!.$ai_provider = 'gemini'
            event.properties!.$ai_model = 'gemini-2.5-pro-preview'
            event.properties!.$ai_input_tokens = 250000 // > 200k triggers large model
            event.properties!.$ai_cache_read_input_tokens = 100000
            event.properties!.$ai_output_tokens = 500

            const result = processAiEvent(event)

            // Model should be switched to gemini-2.5-pro-preview:large
            expect(result.properties!.$ai_model_cost_used).toBe('gemini-2.5-pro-preview:large')

            // Regular tokens: 250000 - 100000 = 150000
            // Input cost: (150000 * 0.0000025) + (100000 * 0.000000625) = 0.375 + 0.0625 = 0.4375
            // Output cost: 500 * 0.000015 = 0.0075
            // Total cost: 0.4375 + 0.0075 = 0.445
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.4375, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.0075, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.445, 6)
        })

        it('handles cache read tokens for gemini-2.0-flash', () => {
            event.properties!.$ai_provider = 'gemini'
            event.properties!.$ai_model = 'gemini-2.0-flash'
            event.properties!.$ai_input_tokens = 1000
            event.properties!.$ai_cache_read_input_tokens = 400
            event.properties!.$ai_output_tokens = 50

            const result = processAiEvent(event)

            // Model will match gemini-2.0-flash-001 from generated-providers.json
            // Regular tokens: 1000 - 400 = 600
            // Input cost: (600 * 1e-7) + (400 * 2.5e-8) = 0.00006 + 0.00001 = 0.00007
            // Output cost: 50 * 4e-7 = 0.00002
            // Total cost: 0.00007 + 0.00002 = 0.00009
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.00007, 7)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.00002, 7)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.00009, 7)
        })

        it('handles zero cache tokens correctly for gemini', () => {
            event.properties!.$ai_provider = 'gemini'
            event.properties!.$ai_model = 'gemini-2.5-pro-preview'
            event.properties!.$ai_input_tokens = 100
            event.properties!.$ai_cache_read_input_tokens = 0
            event.properties!.$ai_output_tokens = 50

            const result = processAiEvent(event)

            // Input cost: 100 * 0.00000125 = 0.000125
            // Output cost: 50 * 0.00001 = 0.0005
            // Total cost: 0.000125 + 0.0005 = 0.000625
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.000125, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.0005, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.000625, 6)
        })

        it('handles combined cache and reasoning tokens for gemini-2.5-pro-preview', () => {
            event.properties!.$ai_provider = 'gemini'
            event.properties!.$ai_model = 'gemini-2.5-pro-preview'
            event.properties!.$ai_input_tokens = 1000
            event.properties!.$ai_cache_read_input_tokens = 400
            event.properties!.$ai_output_tokens = 50
            event.properties!.$ai_reasoning_tokens = 200

            const result = processAiEvent(event)

            // Regular tokens: 1000 - 400 = 600
            // Input cost: (600 * 0.00000125) + (400 * 3.1e-7) = 0.00075 + 0.000124 = 0.000874
            // Output cost: (50 + 200) * 0.00001 = 250 * 0.00001 = 0.0025
            // Total cost: 0.000874 + 0.0025 = 0.003374
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.000874, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.0025, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.003374, 6)
        })

        it('handles gemini-2.5-flash with cache from generated providers', () => {
            event.properties!.$ai_provider = 'gemini'
            event.properties!.$ai_model = 'gemini-2.5-flash'
            event.properties!.$ai_input_tokens = 1000
            event.properties!.$ai_cache_read_input_tokens = 400
            event.properties!.$ai_output_tokens = 50
            event.properties!.$ai_reasoning_tokens = 100

            const result = processAiEvent(event)

            // Regular tokens: 1000 - 400 = 600
            // Input cost: (600 * 3e-7) + (400 * 7.5e-8) = 0.00018 + 0.00003 = 0.00021
            // Output cost: (50 + 100) * 0.0000025 = 150 * 0.0000025 = 0.000375
            // Total cost: 0.00021 + 0.000375 = 0.000585
            expect(result.properties!.$ai_input_cost_usd).toBeCloseTo(0.00021, 6)
            expect(result.properties!.$ai_output_cost_usd).toBeCloseTo(0.000375, 6)
            expect(result.properties!.$ai_total_cost_usd).toBeCloseTo(0.000585, 6)
        })
    })
})

describe('normalizeTraceProperties()', () => {
    it('logs warning for invalid trace property types', () => {
        const event: PluginEvent = {
            event: '$ai_span',
            properties: {
                $ai_trace_id: { invalid: 'object' },
                $ai_parent_id: ['invalid', 'array'],
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }

        jest.clearAllMocks()
        normalizeTraceProperties(event)

        expect(mockWarn).toHaveBeenCalledWith('Unexpected type for trace property $ai_trace_id: object')
        expect(mockWarn).toHaveBeenCalledWith('Unexpected type for trace property $ai_parent_id: object')
    })

    it('handles BigInt trace properties', () => {
        const bigIntValue = BigInt('12345678901234567890')
        const event: PluginEvent = {
            event: '$ai_span',
            properties: {
                $ai_trace_id: bigIntValue as any,
                $ai_parent_id: BigInt(123) as any,
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = normalizeTraceProperties(event)
        expect(result.properties!.$ai_trace_id).toBe('12345678901234567890')
        expect(result.properties!.$ai_parent_id).toBe('123')
    })

    it('converts numeric trace_id to string', () => {
        const event: PluginEvent = {
            event: '$ai_span',
            properties: {
                $ai_trace_id: 12345,
                $ai_parent_id: 67890,
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = normalizeTraceProperties(event)
        expect(result.properties!.$ai_trace_id).toBe('12345')
        expect(result.properties!.$ai_parent_id).toBe('67890')
    })

    it('preserves string trace_id', () => {
        const event: PluginEvent = {
            event: '$ai_span',
            properties: {
                $ai_trace_id: 'abc-123',
                $ai_parent_id: 'def-456',
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = normalizeTraceProperties(event)
        expect(result.properties!.$ai_trace_id).toBe('abc-123')
        expect(result.properties!.$ai_parent_id).toBe('def-456')
    })

    it('handles null and undefined values', () => {
        const event: PluginEvent = {
            event: '$ai_span',
            properties: {
                $ai_trace_id: null,
                $ai_parent_id: undefined,
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = normalizeTraceProperties(event)
        expect(result.properties!.$ai_trace_id).toBe(null)
        expect(result.properties!.$ai_parent_id).toBe(undefined)
    })

    it('normalizes span_id and generation_id', () => {
        const event: PluginEvent = {
            event: '$ai_generation',
            properties: {
                $ai_span_id: 111,
                $ai_generation_id: 222,
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = normalizeTraceProperties(event)
        expect(result.properties!.$ai_span_id).toBe('111')
        expect(result.properties!.$ai_generation_id).toBe('222')
    })

    it('handles boolean trace IDs', () => {
        const event: PluginEvent = {
            event: '$ai_span',
            properties: {
                $ai_trace_id: true,
                $ai_parent_id: false,
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = normalizeTraceProperties(event)
        expect(result.properties!.$ai_trace_id).toBe('true')
        expect(result.properties!.$ai_parent_id).toBe('false')
    })

    it('sets arrays to undefined', () => {
        const event: PluginEvent = {
            event: '$ai_span',
            properties: {
                $ai_trace_id: [1, 2, 3],
                $ai_parent_id: ['a', 'b', 'c'],
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = normalizeTraceProperties(event)
        expect(result.properties!.$ai_trace_id).toBe(undefined)
        expect(result.properties!.$ai_parent_id).toBe(undefined)
    })

    it('sets objects to undefined', () => {
        const event: PluginEvent = {
            event: '$ai_span',
            properties: {
                $ai_trace_id: { id: 123, type: 'trace' },
                $ai_parent_id: { nested: { value: 456 } },
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = normalizeTraceProperties(event)
        expect(result.properties!.$ai_trace_id).toBe(undefined)
        expect(result.properties!.$ai_parent_id).toBe(undefined)
    })

    it('handles mixed valid and invalid types', () => {
        const event: PluginEvent = {
            event: '$ai_span',
            properties: {
                $ai_trace_id: 123,
                $ai_parent_id: 'string-id',
                $ai_span_id: [1, 2],
                $ai_generation_id: { id: 'gen' },
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = normalizeTraceProperties(event)
        expect(result.properties!.$ai_trace_id).toBe('123')
        expect(result.properties!.$ai_parent_id).toBe('string-id') // Already a string
        expect(result.properties!.$ai_span_id).toBe(undefined)
        expect(result.properties!.$ai_generation_id).toBe(undefined)
    })

    it('handles event without properties', () => {
        const event: PluginEvent = {
            event: '$ai_span',
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = normalizeTraceProperties(event)
        expect(result).toEqual(event)
    })
})

describe('processAiEvent() trace normalization', () => {
    it('normalizes trace properties for all AI event types', () => {
        const eventTypes = ['$ai_generation', '$ai_embedding', '$ai_span', '$ai_trace', '$ai_metric', '$ai_feedback']

        for (const eventType of eventTypes) {
            const event: PluginEvent = {
                event: eventType,
                properties: {
                    $ai_trace_id: 123,
                    $ai_parent_id: 456,
                    $ai_model: 'testing_model',
                    $ai_input_tokens: 100,
                    $ai_output_tokens: 50,
                },
                ip: '',
                site_url: '',
                team_id: 0,
                now: '',
                distinct_id: '',
                uuid: '',
                timestamp: '',
            }
            const result = processAiEvent(event)
            expect(result.properties!.$ai_trace_id).toBe('123')
            expect(result.properties!.$ai_parent_id).toBe('456')
        }
    })

    it('normalizes trace properties even for non-cost events', () => {
        const event: PluginEvent = {
            event: '$ai_metric',
            properties: {
                $ai_trace_id: 999,
                $ai_metric_name: 'test_metric',
                $ai_metric_value: 42,
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = processAiEvent(event)
        expect(result.properties!.$ai_trace_id).toBe('999')
        // Should not have cost fields added
        expect(result.properties!.$ai_total_cost_usd).toBeUndefined()
    })

    it('does not normalize non-AI events', () => {
        const event: PluginEvent = {
            event: '$pageview',
            properties: {
                $ai_trace_id: 123,
                $ai_parent_id: 456,
            },
            ip: '',
            site_url: '',
            team_id: 0,
            now: '',
            distinct_id: '',
            uuid: '',
            timestamp: '',
        }
        const result = processAiEvent(event)
        // Should not be normalized since it's not an AI event
        expect(result.properties!.$ai_trace_id).toBe(123)
        expect(result.properties!.$ai_parent_id).toBe(456)
    })
})
