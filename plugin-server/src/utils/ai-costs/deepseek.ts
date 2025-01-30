import type { ModelRow } from './types'

export const costs: ModelRow[] = [
    {
        model: 'deepseek-r1-distill-qwen-32b',
        cost: {
            prompt_token: 7e-7,
            completion_token: 7e-7,
        },
    },
    {
        model: 'deepseek-r1-distill-qwen-14b',
        cost: {
            prompt_token: 7.5e-7,
            completion_token: 7.5e-7,
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
            prompt_token: 0.0000065,
            completion_token: 0.000008,
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
            prompt_token: 8.5e-7,
            completion_token: 9e-7,
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
