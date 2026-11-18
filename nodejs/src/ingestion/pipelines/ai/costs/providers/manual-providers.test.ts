import { findCostFromModel } from '~/ingestion/pipelines/ai/costs/cost-model-matching'
import { processCost } from '~/ingestion/pipelines/ai/costs/index'
import { createAIEvent } from '~/ingestion/pipelines/ai/costs/test-helpers'

import { manualCosts } from './manual-providers'

describe('manualCosts', () => {
    const testCases: Array<{
        model: string
        expected: { prompt_token: number; completion_token: number; cache_read_token?: number }
    }> = [
        {
            model: 'gpt-4.5',
            expected: {
                prompt_token: 0.000075,
                completion_token: 0.00015,
            },
        },
        {
            model: 'claude-2',
            expected: {
                prompt_token: 0.000008,
                completion_token: 0.000024,
            },
        },
        {
            model: 'gemini-2.5-pro-preview:large',
            expected: {
                prompt_token: 0.0000025,
                completion_token: 0.000015,
                cache_read_token: 0.00000025,
            },
        },
        {
            model: 'deepseek-v3-fireworks',
            expected: {
                prompt_token: 0.0000009,
                completion_token: 0.0000009,
            },
        },
        {
            model: 'mistral-large-latest',
            expected: {
                prompt_token: 0.0000007,
                completion_token: 0.0000021,
                cache_read_token: 0.00000007,
            },
        },
        {
            model: 'mistral-small-3.2',
            expected: {
                prompt_token: 0.0000001,
                completion_token: 0.0000003,
            },
        },
        {
            model: 'text-embedding-3-small',
            expected: {
                prompt_token: 0.00000002,
                completion_token: 0,
            },
        },
        {
            model: 'text-embedding-3-large',
            expected: {
                prompt_token: 0.00000013,
                completion_token: 0,
            },
        },
        {
            model: 'text-embedding-ada-002',
            expected: {
                prompt_token: 0.0000001,
                completion_token: 0,
            },
        },
    ]

    it.each(testCases)('has expected costs for $model', ({ model, expected }) => {
        const modelEntry = manualCosts.find((entry) => entry.model === model)

        expect(modelEntry).toBeDefined()
        expect(modelEntry?.cost.default.prompt_token).toBe(expected.prompt_token)
        expect(modelEntry?.cost.default.completion_token).toBe(expected.completion_token)

        if (expected.cache_read_token !== undefined) {
            expect(modelEntry?.cost.default.cache_read_token).toBe(expected.cache_read_token)
        }
    })

    // Rows generated from llm-prices by `pnpm update-ai-costs`, priced end to end.
    describe('direct-provider pricing through ingestion', () => {
        it('prices mistral-large-latest at the Mistral Large 4 list rate', () => {
            const result = processCost(
                createAIEvent({
                    $ai_provider: 'mistral',
                    $ai_model: 'mistral-large-latest',
                    $ai_input_tokens: 1_000_000,
                    $ai_output_tokens: 1_000_000,
                })
            )

            expect(result.properties.$ai_model_cost_used).toBe('mistral-large-latest')
            expect(result.properties.$ai_input_cost_usd).toBeCloseTo(0.7, 8)
            expect(result.properties.$ai_output_cost_usd).toBeCloseTo(2.1, 8)
            expect(result.properties.$ai_total_cost_usd).toBeCloseTo(2.8, 8)
        })

        it('prices cache reads above 200k Gemini 2.5 Pro input tokens at the long-context cache rate', () => {
            const result = processCost(
                createAIEvent({
                    $ai_provider: 'google',
                    $ai_model: 'gemini-2.5-pro-preview',
                    $ai_input_tokens: 300_000,
                    $ai_cache_read_input_tokens: 100_000,
                    $ai_output_tokens: 1_000,
                })
            )

            expect(result.properties.$ai_model_cost_used).toBe('gemini-2.5-pro-preview:large')
            // (200,000 uncached x $2.50 + 100,000 cached x $0.25) / 1M
            expect(result.properties.$ai_input_cost_usd).toBeCloseTo(0.525, 8)
            expect(result.properties.$ai_output_cost_usd).toBeCloseTo(0.015, 8)
        })
    })

    // These TTS models accept text input and emit audio output. They must resolve
    // their own price rather than fuzzy-matching the ordinary Gemini text model.
    describe('Gemini TTS pricing through ingestion', () => {
        it.each([
            ['gemini-2.5-pro-preview-tts', 0.000001, 0.00002],
            ['gemini-3.1-flash-tts-preview', 0.000001, 0.00002],
        ])('prices %s using its dedicated published audio rate', (model, inputRate, audioRate) => {
            for (const provider of ['google', 'gemini', 'google-ai-studio']) {
                for (const usage of [
                    { candidatesTokensDetails: [{ modality: 'AUDIO', tokenCount: 800 }] },
                    { output_tokens_by_modality: [{ modality: 'audio', tokens: 800 }] },
                ]) {
                    const event = createAIEvent({
                        $ai_provider: provider,
                        $ai_model: model,
                        $ai_input_tokens: 100,
                        $ai_output_tokens: 800,
                        $ai_usage: usage,
                    })
                    const resolved = findCostFromModel(model, event.properties)
                    expect(resolved?.cost.model).toBe(model)
                    expect(resolved?.cost.cost.audio_output).toBe(audioRate)

                    const result = processCost(event)

                    expect(result.properties.$ai_audio_output_tokens).toBe(800)
                    expect(result.properties.$ai_input_cost_usd).toBeCloseTo(100 * inputRate, 8)
                    expect(result.properties.$ai_output_cost_usd).toBeCloseTo(800 * audioRate, 8)
                    expect(result.properties.$ai_total_cost_usd).toBeCloseTo(100 * inputRate + 800 * audioRate, 8)
                    expect(result.properties.$ai_usage).toBeUndefined()
                }
            }
        })

        it.each(['gemini-2.5-pro-preview-tts', 'google/gemini-3.1-flash-tts-preview'])(
            'prices audio-only %s even without a modality breakdown',
            (model) => {
                const result = processCost(createAIEvent({ $ai_model: model, $ai_output_tokens: 800 }))

                expect(result.properties.$ai_output_cost_usd).toBeCloseTo(0.016, 8)
                expect(result.properties.$ai_input_cost_usd).toBeUndefined()
                expect(result.properties.$ai_cost_model_provider).toBe('default')
            }
        )

        it('labels an unlisted provider as fallback pricing rather than verified Vertex pricing', () => {
            const result = processCost(
                createAIEvent({
                    $ai_provider: 'vertex',
                    $ai_model: 'gemini-3.1-flash-tts-preview',
                    $ai_output_tokens: 800,
                })
            )

            expect(result.properties.$ai_cost_model_provider).toBe('default')
            expect(result.properties.$ai_output_cost_usd).toBeCloseTo(0.016, 8)
        })
    })
})
