import type { ModelRow } from './types'

export const costs: ModelRow[] = [
    {
        model: 'mistral-small-24b-instruct-2501',
        cost: {
            prompt_token: 1e-7,
            completion_token: 3e-7,
        },
    },
    {
        model: 'codestral-2501',
        cost: {
            prompt_token: 3e-7,
            completion_token: 9e-7,
        },
    },
    {
        model: 'mistral-large-2411',
        cost: {
            prompt_token: 0.000002,
            completion_token: 0.000006,
        },
    },
    {
        model: 'mistral-large-2407',
        cost: {
            prompt_token: 0.000002,
            completion_token: 0.000006,
        },
    },
    {
        model: 'pixtral-large-2411',
        cost: {
            prompt_token: 0.000002,
            completion_token: 0.000006,
        },
    },
    {
        model: 'ministral-8b',
        cost: {
            prompt_token: 1e-7,
            completion_token: 1e-7,
        },
    },
    {
        model: 'ministral-3b',
        cost: {
            prompt_token: 4e-8,
            completion_token: 4e-8,
        },
    },
    {
        model: 'pixtral-12b',
        cost: {
            prompt_token: 1e-7,
            completion_token: 1e-7,
        },
    },
    {
        model: 'mistral-nemo',
        cost: {
            prompt_token: 3.5e-8,
            completion_token: 8e-8,
        },
    },
    {
        model: 'codestral-mamba',
        cost: {
            prompt_token: 2.5e-7,
            completion_token: 2.5e-7,
        },
    },
    {
        model: 'mistral-7b-instruct:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'mistral-7b-instruct',
        cost: {
            prompt_token: 3e-8,
            completion_token: 5.5e-8,
        },
    },
    {
        model: 'mistral-7b-instruct:nitro',
        cost: {
            prompt_token: 7e-8,
            completion_token: 7e-8,
        },
    },
    {
        model: 'mistral-7b-instruct-v0.3',
        cost: {
            prompt_token: 3e-8,
            completion_token: 5.5e-8,
        },
    },
    {
        model: 'mixtral-8x22b-instruct',
        cost: {
            prompt_token: 9e-7,
            completion_token: 9e-7,
        },
    },
    {
        model: 'mistral-large',
        cost: {
            prompt_token: 0.000002,
            completion_token: 0.000006,
        },
    },
    {
        model: 'mistral-small',
        cost: {
            prompt_token: 2e-7,
            completion_token: 6e-7,
        },
    },
    {
        model: 'mistral-tiny',
        cost: {
            prompt_token: 2.5e-7,
            completion_token: 2.5e-7,
        },
    },
    {
        model: 'mistral-medium',
        cost: {
            prompt_token: 0.00000275,
            completion_token: 0.0000081,
        },
    },
    {
        model: 'mixtral-8x7b',
        cost: {
            prompt_token: 6e-7,
            completion_token: 6e-7,
        },
    },
    {
        model: 'mixtral-8x7b-instruct',
        cost: {
            prompt_token: 2.4e-7,
            completion_token: 2.4e-7,
        },
    },
    {
        model: 'mixtral-8x7b-instruct:nitro',
        cost: {
            prompt_token: 5e-7,
            completion_token: 5e-7,
        },
    },
    {
        model: 'mistral-7b-instruct-v0.1',
        cost: {
            prompt_token: 2e-7,
            completion_token: 2e-7,
        },
    },
]
