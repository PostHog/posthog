import type { ModelRow } from './types'

export const costs: ModelRow[] = [
    {
        model: 'sonar-reasoning',
        cost: {
            prompt_token: 0.000001,
            completion_token: 0.000005,
        },
    },
    {
        model: 'sonar',
        cost: {
            prompt_token: 0.000001,
            completion_token: 0.000001,
        },
    },
    {
        model: 'llama-3.1-sonar-huge-128k-online',
        cost: {
            prompt_token: 0.000005,
            completion_token: 0.000005,
        },
    },
    {
        model: 'llama-3.1-sonar-small-128k-chat',
        cost: {
            prompt_token: 2e-7,
            completion_token: 2e-7,
        },
    },
    {
        model: 'llama-3.1-sonar-large-128k-chat',
        cost: {
            prompt_token: 0.000001,
            completion_token: 0.000001,
        },
    },
    {
        model: 'llama-3.1-sonar-large-128k-online',
        cost: {
            prompt_token: 0.000001,
            completion_token: 0.000001,
        },
    },
    {
        model: 'llama-3.1-sonar-small-128k-online',
        cost: {
            prompt_token: 2e-7,
            completion_token: 2e-7,
        },
    },
]
