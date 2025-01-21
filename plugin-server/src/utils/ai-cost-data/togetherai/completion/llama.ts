/**
 *
 * DO NOT EDIT THIS FILE UNLESS IT IS IN /costs
 */

import { ModelRow } from '../../../../types'

export const costs: ModelRow[] = [
    {
        model: {
            operator: 'equals',
            value: 'meta-llama/Llama-2-70b-hf',
        },
        cost: {
            prompt_token: 0.0000009,
            completion_token: 0.0000009,
        },
    },

    {
        model: {
            operator: 'equals',
            value: 'meta-llama/Llama-2-13b-hf',
        },
        cost: {
            prompt_token: 0.000000225,
            completion_token: 0.000000225,
        },
    },

    {
        model: {
            operator: 'equals',
            value: 'meta-llama/Llama-2-7b-hf',
        },
        cost: {
            prompt_token: 0.0000002,
            completion_token: 0.0000002,
        },
    },

    {
        model: {
            operator: 'equals',
            value: 'meta-llama/Meta-Llama-3-70B',
        },
        cost: {
            prompt_token: 0.0000009,
            completion_token: 0.0000009,
        },
    },

    {
        model: {
            operator: 'equals',
            value: 'meta-llama/Llama-3-8b-hf',
        },
        cost: {
            prompt_token: 0.0000002,
            completion_token: 0.0000002,
        },
    },

    {
        model: {
            operator: 'equals',
            value: 'togethercomputer/LLaMA-2-7B-32K',
        },
        cost: {
            prompt_token: 0.0000002,
            completion_token: 0.0000002,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo',
        },
        cost: {
            prompt_token: 0.0000002,
            completion_token: 0.0000002,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo',
        },
        cost: {
            prompt_token: 0.00000088,
            completion_token: 0.00000088,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo',
        },
        cost: {
            prompt_token: 0.000005,
            completion_token: 0.000005,
        },
    },
    {
        model: {
            operator: 'includes',
            value: 'togethercomputer/Meta-Llama-3.1-8B-Instruct-Reference',
        },
        cost: {
            prompt_token: 0.0000002,
            completion_token: 0.00000018,
        },
    },
    {
        model: {
            operator: 'includes',
            value: 'togethercomputer/Meta-Llama-3.1-70B-Instruct-Turbo',
        },
        cost: {
            prompt_token: 0.00000088,
            completion_token: 0.00000088,
        },
    },
    {
        model: {
            operator: 'includes',
            value: 'togethercomputer/Meta-Llama-3.1-405B-Instruct-Turbo',
        },
        cost: {
            prompt_token: 0.000005,
            completion_token: 0.000005,
        },
    },
]
