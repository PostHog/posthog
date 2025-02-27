import type { ModelRow } from './types'

export const costs: ModelRow[] = [
    {
        model: 'deepseek-r1-distill-llama-8b',
        cost: {
            prompt_token: 0.00000004,
            completion_token: 0.00000004,
        },
    },
    {
        model: 'deepseek-r1-distill-qwen-1.5b',
        cost: {
            prompt_token: 0.00000018,
            completion_token: 0.00000018,
        },
    },
    {
        model: 'deepseek-r1-distill-qwen-32b',
        cost: {
            prompt_token: 0.00000012,
            completion_token: 0.00000018,
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
        model: 'deepseek-r1-distill-llama-70b:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'deepseek-r1-distill-llama-70b',
        cost: {
            prompt_token: 0.00000023,
            completion_token: 0.00000069,
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
            prompt_token: 0.0000008,
            completion_token: 0.0000024,
        },
    },
    {
        model: 'deepseek-chat:free',
        cost: {
            prompt_token: 0,
            completion_token: 0,
        },
    },
    {
        model: 'deepseek-chat',
        cost: {
            prompt_token: 0.00000125,
            completion_token: 0.00000125,
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
