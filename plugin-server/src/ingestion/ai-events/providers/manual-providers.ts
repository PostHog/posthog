import type { ModelRow } from './types'

export const manualCosts: ModelRow[] = [
    {
        model: 'gpt-4.5',
        provider: 'openai',
        cost: {
            prompt_token: 0.000075,
            completion_token: 0.00015,
        },
    },
    {
        model: 'claude-3-5-haiku',
        provider: 'anthropic',
        cost: {
            prompt_token: 8e-7,
            completion_token: 0.000004,
            cache_read_token: 8e-8,
            cache_write_token: 0.000001,
        },
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
        model: 'claude-3-7-sonnet',
        provider: 'anthropic',
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000015,
            cache_read_token: 3e-7,
            cache_write_token: 0.00000375,
        },
    },
    {
        model: 'claude-2',
        provider: 'anthropic',
        cost: {
            prompt_token: 0.000008,
            completion_token: 0.000024,
        },
    },
    // Pricing for >200k for Gemini 2.5 Pro
    {
        model: 'gemini-2.5-pro-preview:large',
        provider: 'gemini',
        cost: {
            prompt_token: 0.0000025,
            completion_token: 0.000015,
            cache_read_token: 0.000000625,
        },
    },
    // Other
    {
        model: 'deepseek-v3-fireworks',
        provider: 'fireworks',
        cost: {
            prompt_token: 0.0000009,
            completion_token: 0.0000009,
        },
    },
]
