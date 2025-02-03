import type { ModelRow } from './types'

export const costs: ModelRow[] = [
    {
        model: 'deepseek-r1-distill-qwen-1.5b',
        cost: {
            prompt_token: 1.8e-7,
            completion_token: 1.8e-7,
        },
    },
    {
        model: 'deepseek-r1-distill-qwen-32b',
        cost: {
            prompt_token: 5e-7,
            completion_token: 0.00000488,
        },
    },
    {
        model: 'deepseek-r1-distill-qwen-14b',
        cost: {
            prompt_token: 0.0000016,
            completion_token: 0.0000016,
        },
    },
    {
        model: 'deepseek-r1-distill-llama-70b',
        cost: {
            prompt_token: 2.3e-7,
            completion_token: 6.9e-7,
        },
    },
    {
        model: 'deepseek-r1:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'deepseek-r1',
        cost: {
            prompt_token: 8e-7,
            completion_token: 0.0000024,
        },
    },
    {
        model: 'deepseek-r1:nitro',
        cost: {
            prompt_token: 0.000007,
            completion_token: 0.000007,
        },
    },
    {
        model: 'deepseek-chat',
        cost: {
            prompt_token: 5e-7,
            completion_token: 0.0000015,
        },
    },
    {
        model: 'deepseek-chat-v2.5',
        cost: {
            prompt_token: 0.000002,
            completion_token: 0.000002,
        },
    },
]
