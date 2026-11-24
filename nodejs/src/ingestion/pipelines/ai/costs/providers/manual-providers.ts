import type { ModelCost, ModelCostRow } from './types'

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
                cache_read_token: 0.00000025,
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
    // GPT Image 2 is absent from OpenRouter; manual rates: https://developers.openai.com/api/docs/pricing
    ...['gpt-image-2', 'gpt-image-2-2026-04-21'].map((model) => ({
        model,
        cost: {
            default: {
                prompt_token: 0.000005,
                completion_token: 0.00003,
                cache_read_token: 0.00000125,
                image: 0.000008,
                input_image_cache: 0.000002,
                image_output: 0.00003,
            },
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
                prompt_token: 0.0000007,
                completion_token: 0.0000021,
                cache_read_token: 0.00000007,
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

// OpenAI bills the whole request at its long-context rates once the prompt is above 272K input tokens.
// USD per 1M tokens from the "Long" context-length view of https://developers.openai.com/api/docs/pricing,
// as [input, cached input, cache write, output]. A null is a rate that OpenAI does not publish.
type PerMillionRates = [input: number, cachedInput: number | null, cacheWrite: number | null, output: number]

const OPENAI_LONG_CONTEXT_RATES: Record<
    string,
    { standard: PerMillionRates; priority?: PerMillionRates; flex?: PerMillionRates }
> = {
    'gpt-6.2-astra': { standard: [16, 0.8, 20, 60], priority: [32, 1.6, 40, 120] },
    'gpt-6.2-sol': { standard: [4, 0.2, 5, 15], priority: [8, 0.4, 10, 30] },
    'gpt-6-astra': { standard: [20, 2, 25, 75], priority: [40, 4, 50, 150], flex: [10, 1, 12.5, 37.5] },
    'gpt-6.1-sol': { standard: [4, 0.2, 5, 15], priority: [8, 0.4, 10, 30], flex: [2, 0.1, 2.5, 7.5] },
    'gpt-6.1-terra': { standard: [2, 0.1, 2.5, 7.5], priority: [4, 0.2, 5, 15], flex: [1, 0.05, 1.25, 3.75] },
    'gpt-6-luna': {
        standard: [0.2, 0.02, 0.25, 0.75],
        priority: [0.4, 0.04, 0.5, 1.5],
        flex: [0.1, 0.01, 0.125, 0.375],
    },
    'gpt-6-sol': { standard: [4, 0.4, 5, 15], priority: [8, 0.8, 10, 30], flex: [2, 0.2, 2.5, 7.5] },
    'gpt-5.6-sol': { standard: [8, 0.8, 10, 30], priority: [16, 1.6, 20, 60], flex: [4, 0.4, 5, 15] },
    'gpt-5.6-terra': { standard: [4, 0.4, 5, 18], priority: [8, 0.8, 10, 36], flex: [2, 0.2, 2.5, 9] },
    'gpt-5.6-luna': { standard: [0.4, 0.04, 0.5, 1.8], priority: [0.8, 0.08, 1, 3.6], flex: [0.2, 0.02, 0.25, 0.9] },
    'gpt-5.5': { standard: [10, 1, null, 45], flex: [5, 0.5, null, 22.5] },
    'gpt-5.5-pro': { standard: [60, null, null, 270] },
    'gpt-5.4': { standard: [5, 0.5, null, 22.5], flex: [2.5, 0.25, null, 11.25] },
    'gpt-5.4-pro': { standard: [60, null, null, 270] },
}

// The web search tool costs $10 per 1K calls whatever the prompt length.
const OPENAI_WEB_SEARCH_PER_CALL = 0.01

// Parsing the decimal exponent keeps 0.4 per 1M at exactly 4e-7, where 0.4 / 1e6 is not.
const perToken = (usdPerMillion: number): number => Number(`${usdPerMillion}e-6`)

const toModelCost = ([input, cachedInput, cacheWrite, output]: PerMillionRates): ModelCost => ({
    prompt_token: perToken(input),
    completion_token: perToken(output),
    ...(cachedInput !== null && { cache_read_token: perToken(cachedInput) }),
    ...(cacheWrite !== null && { cache_write_token: perToken(cacheWrite) }),
    web_search: OPENAI_WEB_SEARCH_PER_CALL,
})

export const openAILongContextModels: string[] = Object.keys(OPENAI_LONG_CONTEXT_RATES)

const openAILongContextCosts: ModelCostRow[] = Object.entries(OPENAI_LONG_CONTEXT_RATES).map(
    ([model, { standard, priority, flex }]) => ({
        model: `${model}:large`,
        cost: {
            default: toModelCost(standard),
            openai: toModelCost(standard),
            ...(priority && { 'openai-fast': toModelCost(priority) }),
            ...(flex && { 'openai-flex': toModelCost(flex) }),
        },
    })
)

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

export const manualCosts: ModelCostRow[] = [...manualProviderCosts, ...openAILongContextCosts, ...embeddingModelCosts]
