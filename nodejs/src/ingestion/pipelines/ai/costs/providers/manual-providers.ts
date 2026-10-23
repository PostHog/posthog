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
    // Gemini TTS models accept text-only input and emit audio-only output.
    // Standard Gemini Developer API rates, USD per token:
    // https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-pro-preview-tts
    // https://ai.google.dev/gemini-api/docs/pricing#gemini-3.1-flash-tts-preview
    // The completion rate also prices audio when a client omits the modality breakdown.
    ...['gemini-2.5-pro-preview-tts', 'gemini-3.1-flash-tts-preview'].map((model) => ({
        model,
        cost: {
            default: { prompt_token: 0.000001, completion_token: 0.00002, audio_output: 0.00002 },
            'google-ai-studio': { prompt_token: 0.000001, completion_token: 0.00002, audio_output: 0.00002 },
        },
    })),
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
