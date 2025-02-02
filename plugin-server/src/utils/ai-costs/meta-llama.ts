import type { ModelRow } from './types'

export const costs: ModelRow[] = [
    {
        model: 'llama-3.3-70b-instruct',
        cost: {
            prompt_token: 1.2e-7,
            completion_token: 3e-7,
        },
    },
    {
        model: 'llama-3.2-3b-instruct:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'llama-3.2-3b-instruct',
        cost: {
            prompt_token: 1.5e-8,
            completion_token: 2.5e-8,
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
            prompt_token: 1e-8,
            completion_token: 1e-8,
        },
    },
    {
        model: 'llama-3.2-90b-vision-instruct:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'llama-3.2-90b-vision-instruct',
        cost: {
            prompt_token: 9e-7,
            completion_token: 9e-7,
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
            prompt_token: 5.5e-8,
            completion_token: 5.5e-8,
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
        model: 'llama-3.1-405b-instruct:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'llama-3.1-405b-instruct',
        cost: {
            prompt_token: 8e-7,
            completion_token: 8e-7,
        },
    },
    {
        model: 'llama-3.1-405b-instruct:nitro',
        cost: {
            prompt_token: 0.00001462,
            completion_token: 0.00001462,
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
            prompt_token: 2e-8,
            completion_token: 5e-8,
        },
    },
    {
        model: 'llama-3.1-70b-instruct:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'llama-3.1-70b-instruct',
        cost: {
            prompt_token: 1.2e-7,
            completion_token: 3e-7,
        },
    },
    {
        model: 'llama-3.1-70b-instruct:nitro',
        cost: {
            prompt_token: 0.00000325,
            completion_token: 0.00000325,
        },
    },
    {
        model: 'llama-guard-2-8b',
        cost: {
            prompt_token: 2e-7,
            completion_token: 2e-7,
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
            prompt_token: 3e-8,
            completion_token: 6e-8,
        },
    },
    {
        model: 'llama-3-8b-instruct:extended',
        cost: {
            prompt_token: 1.875e-7,
            completion_token: 0.000001125,
        },
    },
    {
        model: 'llama-3-8b-instruct:nitro',
        cost: {
            prompt_token: 2e-7,
            completion_token: 2e-7,
        },
    },
    {
        model: 'llama-3-70b-instruct',
        cost: {
            prompt_token: 2.3e-7,
            completion_token: 4e-7,
        },
    },
    {
        model: 'llama-3-70b-instruct:nitro',
        cost: {
            prompt_token: 8.8e-7,
            completion_token: 8.8e-7,
        },
    },
    {
        model: 'llama-2-13b-chat',
        cost: {
            prompt_token: 2.2e-7,
            completion_token: 2.2e-7,
        },
    },
    {
        model: 'llama-2-70b-chat',
        cost: {
            prompt_token: 9e-7,
            completion_token: 9e-7,
        },
    },
]
