import type { ModelCostRow } from './types'

const manualProviderCosts: ModelCostRow[] = [
    {
        model: 'gpt-4.5',
        cost: {
            default: {
                prompt_token: 0.000075,
                completion_token: 0.00015,
            },
        },
    },
    {
        model: 'claude-2',
        cost: {
            default: {
                prompt_token: 0.000008,
                completion_token: 0.000024,
            },
        },
    },
    // OpenAI flex service tier (https://developers.openai.com/api/docs/pricing?latest-pricing=flex,
    // September 2026). The upstream sync carries :batch rows but no :flex ones, so these are
    // manual; keep them matching that page.
    {
        model: 'gpt-5.6-sol:flex',
        cost: {
            default: {
                prompt_token: 0.000002,
                completion_token: 0.00001,
                cache_read_token: 0.0000002,
                cache_write_token: 0.0000025,
            },
        },
    },
    {
        model: 'gpt-5.6-terra:flex',
        cost: {
            default: {
                prompt_token: 0.000001,
                completion_token: 0.000006,
                cache_read_token: 0.0000001,
                cache_write_token: 0.00000125,
            },
        },
    },
    {
        model: 'gpt-5.6-luna:flex',
        cost: {
            default: {
                prompt_token: 0.0000001,
                completion_token: 0.0000006,
                cache_read_token: 0.00000001,
                cache_write_token: 0.000000125,
            },
        },
    },
    {
        model: 'gpt-5.5:flex',
        cost: {
            default: {
                prompt_token: 0.0000025,
                completion_token: 0.000015,
                cache_read_token: 0.00000025,
            },
        },
    },
    {
        model: 'gpt-5.4:flex',
        cost: {
            default: {
                prompt_token: 0.00000125,
                completion_token: 0.0000075,
                cache_read_token: 0.00000013,
            },
        },
    },
    {
        model: 'gpt-5.4-mini:flex',
        cost: {
            default: {
                prompt_token: 0.000000375,
                completion_token: 0.00000225,
                cache_read_token: 0.0000000375,
            },
        },
    },
    {
        model: 'gpt-5.4-nano:flex',
        cost: {
            default: {
                prompt_token: 0.0000001,
                completion_token: 0.000000625,
                cache_read_token: 0.00000001,
            },
        },
    },
    {
        model: 'gpt-5.2:flex',
        cost: {
            default: {
                prompt_token: 0.000000875,
                completion_token: 0.000007,
                cache_read_token: 0.0000000875,
            },
        },
    },
    {
        model: 'gpt-5.1:flex',
        cost: {
            default: {
                prompt_token: 0.000000625,
                completion_token: 0.000005,
                cache_read_token: 0.0000000625,
            },
        },
    },
    {
        model: 'gpt-5:flex',
        cost: {
            default: {
                prompt_token: 0.000000625,
                completion_token: 0.000005,
                cache_read_token: 0.0000000625,
            },
        },
    },
    {
        model: 'gpt-5-mini:flex',
        cost: {
            default: {
                prompt_token: 0.000000125,
                completion_token: 0.000001,
                cache_read_token: 0.0000000125,
            },
        },
    },
    {
        model: 'gpt-5-nano:flex',
        cost: {
            default: {
                prompt_token: 0.000000025,
                completion_token: 0.0000002,
                cache_read_token: 0.0000000025,
            },
        },
    },
    {
        model: 'o4-mini:flex',
        cost: {
            default: {
                prompt_token: 0.00000055,
                completion_token: 0.0000022,
                cache_read_token: 0.000000138,
            },
        },
    },
    {
        model: 'o3:flex',
        cost: {
            default: {
                prompt_token: 0.000001,
                completion_token: 0.000004,
                cache_read_token: 0.00000025,
            },
        },
    },
    // Pricing for >200k for Gemini 2.5 Pro
    {
        model: 'gemini-2.5-pro-preview:large',
        cost: {
            default: {
                prompt_token: 0.0000025,
                completion_token: 0.000015,
                cache_read_token: 0.000000625,
            },
        },
    },
    // Other
    {
        model: 'deepseek-v3-fireworks',
        cost: {
            default: {
                prompt_token: 0.0000009,
                completion_token: 0.0000009,
            },
        },
    },
    {
        model: 'mistral-large-latest',
        cost: {
            default: {
                prompt_token: 0.000002,
                completion_token: 0.000006,
            },
        },
    },
    {
        model: 'mistral-small-3.2',
        cost: {
            default: {
                prompt_token: 0.0000001,
                completion_token: 0.0000003,
            },
        },
    },
]

const embeddingModelCosts: ModelCostRow[] = [
    {
        model: 'text-embedding-3-small',
        cost: {
            // 2c per 1M tokens
            default: {
                prompt_token: 0.00000002,
                completion_token: 0,
            },
        },
    },
    {
        model: 'text-embedding-3-large',
        cost: {
            default: {
                prompt_token: 0.00000013,
                completion_token: 0,
            },
        },
    },
    {
        model: 'text-embedding-ada-002',
        cost: {
            default: {
                prompt_token: 0.0000001,
                completion_token: 0,
            },
        },
    },
]

export const manualCosts: ModelCostRow[] = [...manualProviderCosts, ...embeddingModelCosts]
