import type { ModelRow } from './types'

export const embeddingCosts: ModelRow[] = [
    // OpenAI
    {
        model: 'text-embedding-3-small',
        cost: {
            // 2c per 1M tokens
            prompt_token: 0.00000002,
            completion_token: 0,
        },
    },
    {
        model: 'text-embedding-3-large',
        cost: {
            prompt_token: 0.00000013,
            completion_token: 0,
        },
    },
    {
        model: 'text-embedding-ada-002',
        cost: {
            prompt_token: 0.0000001,
            completion_token: 0,
        },
    },
]
