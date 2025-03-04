import type { ModelRow } from './types'

export const costs: ModelRow[] = [
    {
        model: 'gpt-4.5',
        cost: {
            prompt_token: 0.000075,
            completion_token: 0.00015,
        },
    },
]
