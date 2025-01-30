import type { ModelRow } from './types'

export const costs: ModelRow[] = [
    {
        model: 'command-r7b-12-2024',
        cost: {
            prompt_token: 3.75e-8,
            completion_token: 1.5e-7,
        },
    },
    {
        model: 'command-r-08-2024',
        cost: {
            prompt_token: 1.425e-7,
            completion_token: 5.7e-7,
        },
    },
    {
        model: 'command-r-plus-08-2024',
        cost: {
            prompt_token: 0.000002375,
            completion_token: 0.0000095,
        },
    },
    {
        model: 'command-r-plus',
        cost: {
            prompt_token: 0.00000285,
            completion_token: 0.00001425,
        },
    },
    {
        model: 'command-r-plus-04-2024',
        cost: {
            prompt_token: 0.00000285,
            completion_token: 0.00001425,
        },
    },
    {
        model: 'command',
        cost: {
            prompt_token: 9.5e-7,
            completion_token: 0.0000019,
        },
    },
    {
        model: 'command-r',
        cost: {
            prompt_token: 4.75e-7,
            completion_token: 0.000001425,
        },
    },
    {
        model: 'command-r-03-2024',
        cost: {
            prompt_token: 4.75e-7,
            completion_token: 0.000001425,
        },
    },
]
