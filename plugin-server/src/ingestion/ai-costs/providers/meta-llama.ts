import type { ModelRow } from './types'

export const costs: ModelRow[] = [
    {
        model: 'llama-guard-3-8b',
        cost: {
            prompt_token: 0.0000003,
            completion_token: 0.0000003,
        },
    },
    {
        model: 'llama-3.3-70b-instruct:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'llama-3.3-70b-instruct',
        cost: {
            prompt_token: 0.00000012,
            completion_token: 0.0000003,
        },
    },
    {
        model: 'llama-3.2-3b-instruct',
        cost: {
            prompt_token: 0.000000015,
            completion_token: 0.000000025,
        },
    },
    {
        model: 'llama-3.2-11b-vision-instruct:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'llama-3.2-11b-vision-instruct',
        cost: {
            prompt_token: 0.000000055,
            completion_token: 0.000000055,
        },
    },
    {
        model: 'llama-3.2-90b-vision-instruct',
        cost: {
            prompt_token: 0.0000008,
            completion_token: 0.0000016,
        },
    },
    {
        model: 'llama-3.2-1b-instruct:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'llama-3.2-1b-instruct',
        cost: {
            prompt_token: 0.00000001,
            completion_token: 0.00000001,
        },
    },
    {
        model: 'llama-3.1-405b',
        cost: {
            prompt_token: 0.000002,
            completion_token: 0.000002,
        },
    },
    {
        model: 'llama-3.1-405b-instruct',
        cost: {
            prompt_token: 0.0000008,
            completion_token: 0.0000008,
        },
    },
    {
        model: 'llama-3.1-8b-instruct:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'llama-3.1-8b-instruct',
        cost: {
            prompt_token: 0.00000002,
            completion_token: 0.00000005,
        },
    },
    {
        model: 'llama-3.1-70b-instruct',
        cost: {
            prompt_token: 0.00000012,
            completion_token: 0.0000003,
        },
    },
    {
        model: 'llama-guard-2-8b',
        cost: {
            prompt_token: 0.0000002,
            completion_token: 0.0000002,
        },
    },
    {
        model: 'llama-3-8b-instruct:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'llama-3-8b-instruct',
        cost: {
            prompt_token: 0.00000003,
            completion_token: 0.00000006,
        },
    },
    {
        model: 'llama-3-70b-instruct',
        cost: {
            prompt_token: 0.00000023,
            completion_token: 0.0000004,
        },
    },
    {
        model: 'llama-2-13b-chat',
        cost: {
            prompt_token: 0.00000022,
            completion_token: 0.00000022,
        },
    },
    {
        model: 'llama-2-70b-chat',
        cost: {
            prompt_token: 0.0000009,
            completion_token: 0.0000009,
        },
    },
]
