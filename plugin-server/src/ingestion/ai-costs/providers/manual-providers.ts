import type { ModelRow } from './types'

export const manualCosts: ModelRow[] = [
    // OpenAI
    {
        model: 'gpt-4.5',
        cost: {
            prompt_token: 0.000075,
            completion_token: 0.00015,
        },
    },
    // Anthropic
    {
        model: 'claude-3-5-haiku',
        cost: {
            prompt_token: 8e-7,
            completion_token: 0.000004,
        },
    },
    {
        model: 'claude-3-5-sonnet',
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000015,
        },
    },
    {
        model: 'claude-3-7-sonnet',
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000015,
        },
    },
    {
        model: 'claude-3-opus',
        cost: {
            prompt_token: 0.000015,
            completion_token: 0.000075,
        },
    },
    {
        model: 'claude-2',
        cost: {
            prompt_token: 0.000008,
            completion_token: 0.000024,
        },
    },
    {
        model: 'claude-3.5',
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000015,
        },
    },
    {
        model: 'claude-3.7',
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000015,
        },
    },
    {
        model: 'claude-4',
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000015,
        },
    },
    {
        model: 'claude-opus-4',
        cost: {
            prompt_token: 0.000015,
            completion_token: 0.000075,
        },
    },
    {
        model: 'claude-sonnet-4',
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000015,
        },
    },
    // google gen ai
    {
        model: 'gemini-2.0-flash',
        cost: {
            prompt_token: 0.00000015,
            completion_token: 0.000000075,
        },
    },
    {
        model: 'gemini-2.5-pro-preview',
        cost: {
            prompt_token: 0.00000125,
            completion_token: 0.00001,
        },
    },
    {
        model: 'gemini-2.5-pro-preview:large',
        cost: {
            prompt_token: 0.0000025,
            completion_token: 0.000015,
        },
    },
    // Other
    {
        model: 'deepseek-v3-fireworks',
        cost: {
            prompt_token: 0.0000009,
            completion_token: 0.0000009,
        },
    },
    // testing
    {
        model: 'testing_model',
        cost: {
            prompt_token: 0.1,
            completion_token: 0.1,
        },
    },
]
