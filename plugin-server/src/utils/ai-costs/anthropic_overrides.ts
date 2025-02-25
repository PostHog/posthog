import type { ModelRow } from './types'

export const costs: ModelRow[] = [
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
]
