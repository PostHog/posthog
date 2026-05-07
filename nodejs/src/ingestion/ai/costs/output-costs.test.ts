import { calculateOutputCost } from './output-costs'
import { ResolvedModelCost } from './providers/types'
import { createAIEvent } from './test-helpers'

// Helper function to create a ModelRow with defaults
function createModel(
    model: string,
    provider?: string,
    promptTokenCost?: number,
    completionTokenCost?: number,
    imageOutputCost?: number
): ResolvedModelCost {
    return {
        model,
        provider: provider ?? 'default',
        cost: {
            prompt_token: promptTokenCost ?? 0.000001,
            completion_token: completionTokenCost ?? 0.000002,
            ...(imageOutputCost !== undefined && { image_output: imageOutputCost }),
        },
    }
}

// Helper function to assert cost calculation
function expectCost(result: string, expectedCost: number, precision: number = 6): void {
    expect(parseFloat(result)).toBeCloseTo(expectedCost, precision)
}

describe('calculateOutputCost()', () => {
    describe('basic output cost calculation', () => {
        const basicModel = createModel('gpt-4', 'openai', 0.00003, 0.00006)

        it('calculates output cost without reasoning tokens', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-4',
                $ai_output_tokens: 500,
            })

            const result = calculateOutputCost(event, basicModel)

            expectCost(result, 0.03) // 500 * 0.00006 = 0.03
        })

        it.each([
            { tokens: 0, expectedResult: '0', description: 'returns 0 when output tokens is 0' },
            { tokens: undefined, expectedResult: '0', description: 'returns 0 when output tokens is undefined' },
        ])('$description', ({ tokens, expectedResult }) => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-4',
                ...(tokens !== undefined && { $ai_output_tokens: tokens }),
            })

            const result = calculateOutputCost(event, basicModel)

            expect(result).toBe(expectedResult)
        })

        it('handles very large output token counts', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-4',
                $ai_output_tokens: 1e10,
            })

            const result = calculateOutputCost(event, basicModel)

            expect(parseFloat(result)).toBeGreaterThan(0)
        })
    })

    describe('gemini 2.5 models - reasoning token handling', () => {
        const gemini25ProModel = createModel('gemini-2.5-pro', 'google', 0.00000125, 0.00001)
        const gemini25FlashModel = createModel('gemini-2.5-flash', 'google', 3e-7, 0.0000025)

        it.each([
            {
                model: 'gemini-2.5-pro',
                modelRow: gemini25ProModel,
                outputTokens: 100,
                reasoningTokens: 200,
                expectedCost: 0.003,
                description: 'includes reasoning tokens for gemini-2.5-pro',
            },
            {
                model: 'gemini-2.5-flash',
                modelRow: gemini25FlashModel,
                outputTokens: 50,
                reasoningTokens: 150,
                expectedCost: 0.0005,
                description: 'includes reasoning tokens for gemini-2.5-flash',
            },
        ])('$description', ({ model, modelRow, outputTokens, reasoningTokens, expectedCost }) => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: model,
                $ai_output_tokens: outputTokens,
                $ai_reasoning_tokens: reasoningTokens,
            })

            const result = calculateOutputCost(event, modelRow)

            expectCost(result, expectedCost)
        })

        it.each([
            {
                reasoningTokens: undefined,
                description: 'handles undefined reasoning tokens',
            },
            {
                reasoningTokens: 0,
                description: 'handles zero reasoning tokens',
            },
        ])('$description for gemini-2.5', ({ reasoningTokens }) => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-pro',
                $ai_output_tokens: 100,
                ...(reasoningTokens !== undefined && { $ai_reasoning_tokens: reasoningTokens }),
            })

            const result = calculateOutputCost(event, gemini25ProModel)

            expectCost(result, 0.001) // 100 * 0.00001 = 0.001
        })

        it.each([
            { modelName: 'GEMINI-2.5-PRO', description: 'is case-insensitive for model matching' },
            { modelName: 'gemini-2.5-pro-preview-0514', description: 'handles gemini-2.5 variants with suffixes' },
        ])('$description', ({ modelName }) => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: modelName,
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: 200,
            })

            const result = calculateOutputCost(event, gemini25ProModel)

            expectCost(result, 0.003) // Should include reasoning tokens
        })

        it('handles very large reasoning token counts', () => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-pro',
                $ai_output_tokens: 1000,
                $ai_reasoning_tokens: 1e9,
            })

            const result = calculateOutputCost(event, gemini25ProModel)

            expect(parseFloat(result)).toBeGreaterThan(10000)
        })
    })

    describe('gemini 3 models - reasoning token handling', () => {
        // Real rates from llm-costs.json
        const gemini3FlashModel = createModel('gemini-3-flash-preview', 'google', 5e-7, 3e-6)
        const gemini31ProModel = createModel('gemini-3.1-pro-preview', 'google', 2e-6, 1.2e-5)

        it.each([
            {
                modelName: 'gemini-3-flash-preview',
                modelRow: gemini3FlashModel,
                outputTokens: 2,
                reasoningTokens: 77,
                // (2 + 77) * 3e-6 = 0.000237
                expectedCost: 0.000237,
                description: 'includes reasoning tokens for gemini-3-flash-preview (issue #3160)',
            },
            {
                modelName: 'gemini-3.1-pro-preview',
                modelRow: gemini31ProModel,
                outputTokens: 100,
                reasoningTokens: 200,
                // (100 + 200) * 1.2e-5 = 0.0036
                expectedCost: 0.0036,
                description: 'includes reasoning tokens for gemini-3.1-pro-preview',
            },
        ])('$description', ({ modelName, modelRow, outputTokens, reasoningTokens, expectedCost }) => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: modelName,
                $ai_output_tokens: outputTokens,
                $ai_reasoning_tokens: reasoningTokens,
            })

            const result = calculateOutputCost(event, modelRow)

            expectCost(result, expectedCost)
        })
    })

    describe('gemini 2.0 models - no reasoning token handling', () => {
        const gemini20FlashModel = createModel('gemini-2.0-flash', 'google', 1e-7, 4e-7)

        it.each([
            { modelName: 'gemini-2.0-flash', description: 'does not include reasoning tokens for gemini-2.0' },
            {
                modelName: 'gemini-2.0-flash-001',
                description: 'does not include reasoning tokens for gemini-2.0-flash-001',
            },
        ])('$description', ({ modelName }) => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: modelName,
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: 200,
            })

            const result = calculateOutputCost(event, gemini20FlashModel)

            // Only output tokens, no reasoning: 100 * 4e-7 = 0.00004
            expectCost(result, 0.00004, 7)
        })
    })

    describe('non-gemini models - no reasoning token handling', () => {
        const testCases = [
            {
                name: 'OpenAI',
                model: 'gpt-4o',
                provider: 'openai',
                promptCost: 0.0000025,
                completionCost: 0.00001,
                expectedCost: 0.001,
            },
            {
                name: 'Anthropic',
                model: 'claude-3-5-sonnet',
                provider: 'anthropic',
                promptCost: 0.000003,
                completionCost: 0.000015,
                expectedCost: 0.0015,
            },
            {
                name: 'o1',
                model: 'o1-mini',
                provider: 'openai',
                promptCost: 0.0000011,
                completionCost: 0.0000044,
                expectedCost: 0.00044,
            },
            {
                name: 'custom',
                model: 'custom-model',
                provider: 'custom',
                promptCost: 0.000001,
                completionCost: 0.000002,
                expectedCost: 0.0002,
            },
        ]

        it.each(testCases)(
            'does not include reasoning tokens for $name models',
            ({ model, provider, promptCost, completionCost, expectedCost }) => {
                const modelRow = createModel(model, provider, promptCost, completionCost)
                const event = createAIEvent({
                    $ai_provider: provider,
                    $ai_model: model,
                    $ai_output_tokens: 100,
                    $ai_reasoning_tokens: 200,
                })

                const result = calculateOutputCost(event, modelRow)

                // Only output tokens: 100 * completionCost
                expectCost(result, expectedCost)
            }
        )
    })

    describe('image output tokens - multimodal cost calculation', () => {
        // Gemini 2.5 Flash Image pricing (from Google pricing page):
        // Input: $0.30/1M tokens ($0.0000003/token)
        // Text output: $2.50/1M tokens ($0.0000025/token) - same as 2.5 Flash
        // Image output: $30/1M tokens ($0.00003/token)
        // 1290 tokens per 1024x1024 image = $0.039/image
        const geminiImageModel = createModel(
            'gemini-2.5-flash-image',
            'google',
            0.0000003, // prompt ($0.30/1M)
            0.0000025, // completion/text ($2.50/1M)
            0.00003 // image_output ($30/1M)
        )

        it('calculates separate costs for text and image output tokens', () => {
            // Example: 10 text tokens + 1290 image tokens (1 image)
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-flash-image',
                $ai_output_tokens: 1300, // Total: 10 text + 1290 image
                $ai_image_output_tokens: 1290,
                $ai_text_output_tokens: 10,
            })

            const result = calculateOutputCost(event, geminiImageModel)

            // Expected: (10 * 0.0000025) + (1290 * 0.00003) = 0.000025 + 0.0387 = 0.038725
            expectCost(result, 0.038725, 6)
        })

        it('calculates text tokens from total minus image when text tokens not explicit', () => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-flash-image',
                $ai_output_tokens: 1300, // Total
                $ai_image_output_tokens: 1290, // Image tokens only
                // $ai_text_output_tokens not set
            })

            const result = calculateOutputCost(event, geminiImageModel)

            // Text tokens calculated as: 1300 - 1290 = 10
            // Expected: (10 * 0.0000025) + (1290 * 0.00003) = 0.038725
            expectCost(result, 0.038725, 6)
        })

        it('handles only image output (no text)', () => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-flash-image',
                $ai_output_tokens: 1290,
                $ai_image_output_tokens: 1290,
            })

            const result = calculateOutputCost(event, geminiImageModel)

            // Text tokens: 1290 - 1290 = 0
            // Expected: (0 * 0.0000025) + (1290 * 0.00003) = 0.0387
            expectCost(result, 0.0387, 6)
        })

        it('falls back to standard calculation when no image pricing available', () => {
            const modelWithoutImagePricing = createModel('some-model', 'some-provider', 0.000001, 0.0000025)
            const event = createAIEvent({
                $ai_provider: 'some-provider',
                $ai_model: 'some-model',
                $ai_output_tokens: 1300,
                $ai_image_output_tokens: 1290, // Has image tokens but no image pricing
            })

            const result = calculateOutputCost(event, modelWithoutImagePricing)

            // Falls back to: 1300 * 0.0000025 = 0.00325
            expectCost(result, 0.00325, 6)
        })

        it('handles image output with reasoning tokens for gemini-2.5', () => {
            // Gemini 2.5 Flash Image model with reasoning
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-flash-image',
                $ai_output_tokens: 1500, // Total
                $ai_image_output_tokens: 1290, // Image
                $ai_text_output_tokens: 10, // Text
                $ai_reasoning_tokens: 200, // Reasoning (added to text for Gemini 2.5)
            })

            const result = calculateOutputCost(event, geminiImageModel)

            // Text tokens with reasoning: 10 + 200 = 210
            // Expected: (210 * 0.0000025) + (1290 * 0.00003) = 0.000525 + 0.0387 = 0.039225
            expectCost(result, 0.039225, 6)
        })

        it('handles image output with reasoning tokens for gemini-3', () => {
            // Gemini 3 Pro Image Preview pricing (from llm-costs.json):
            // Text output: $12/1M tokens ($1.2e-5/token)
            // Image output: $120/1M tokens ($1.2e-4/token)
            const gemini3ImageModel = createModel('gemini-3-pro-image-preview', 'google', 2e-6, 1.2e-5, 1.2e-4)
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-3-pro-image-preview',
                $ai_output_tokens: 1500,
                $ai_image_output_tokens: 1290,
                $ai_text_output_tokens: 10,
                $ai_reasoning_tokens: 200,
            })

            const result = calculateOutputCost(event, gemini3ImageModel)

            // Text tokens with reasoning: 10 + 200 = 210
            // Expected: (210 * 1.2e-5) + (1290 * 1.2e-4) = 0.00252 + 0.1548 = 0.15732
            expectCost(result, 0.15732, 5)
        })

        it('handles zero image tokens with image pricing (text only)', () => {
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-flash-image',
                $ai_output_tokens: 500,
                $ai_image_output_tokens: 0, // Explicitly zero
            })

            const result = calculateOutputCost(event, geminiImageModel)

            // Falls back to standard: 500 * 0.0000025 = 0.00125
            expectCost(result, 0.00125, 6)
        })

        it('handles multiple images (large image token count)', () => {
            // 3 images = 3 * 1290 = 3870 tokens
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-flash-image',
                $ai_output_tokens: 3880, // 10 text + 3870 image
                $ai_image_output_tokens: 3870,
                $ai_text_output_tokens: 10,
            })

            const result = calculateOutputCost(event, geminiImageModel)

            // Expected: (10 * 0.0000025) + (3870 * 0.00003) = 0.000025 + 0.1161 = 0.116125
            expectCost(result, 0.116125, 6)
        })
    })

    describe('edge cases', () => {
        const testModel = createModel('test-model')

        it('returns 0 when properties is undefined', () => {
            const event = {
                ...createAIEvent(),
                properties: undefined,
            }

            const result = calculateOutputCost(event, testModel)

            expect(result).toBe('0')
        })

        it.each([
            { value: null, description: 'handles null output tokens' },
            { value: undefined, description: 'handles undefined output tokens (via empty properties)' },
        ])('$description', ({ value }) => {
            const event = createAIEvent(value === undefined ? {} : { $ai_output_tokens: value as any })

            const result = calculateOutputCost(event, testModel)

            expect(result).toBe('0')
        })

        it('handles null reasoning tokens for gemini-2.5', () => {
            const gemini25Model = createModel('gemini-2.5-pro', undefined, 0.00000125, 0.00001)
            const event = createAIEvent({
                $ai_model: 'gemini-2.5-pro',
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: null as any,
            })

            const result = calculateOutputCost(event, gemini25Model)

            // Should treat null as 0: 100 * 0.00001 = 0.001
            expectCost(result, 0.001)
        })

        it('handles negative output tokens', () => {
            const event = createAIEvent({
                $ai_output_tokens: -100,
            })

            const result = calculateOutputCost(event, testModel)

            // Should calculate even with negative (though invalid in practice)
            expect(parseFloat(result)).toBeLessThan(0)
        })

        it('handles negative reasoning tokens for gemini-2.5', () => {
            const gemini25Model = createModel('gemini-2.5-pro', undefined, 0.00000125, 0.00001)
            const event = createAIEvent({
                $ai_model: 'gemini-2.5-pro',
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: -50,
            })

            const result = calculateOutputCost(event, gemini25Model)

            // (100 + (-50)) * 0.00001 = 50 * 0.00001 = 0.0005
            expectCost(result, 0.0005)
        })

        it('handles missing model field for reasoning check', () => {
            const gemini25Model = createModel('gemini-2.5-pro', undefined, 0.00000125, 0.00001)
            const event = createAIEvent({
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: 200,
            })

            const result = calculateOutputCost(event, gemini25Model)

            // Without $ai_model, reasoning tokens won't be added
            // Only output tokens: 100 * 0.00001 = 0.001
            expectCost(result, 0.001)
        })

        it('handles gemini-2.5 model variant names', () => {
            const gemini25FlashModel = createModel('gemini-2.5-flash', 'google', 3e-7, 0.0000025)
            const event = createAIEvent({
                $ai_provider: 'google',
                $ai_model: 'gemini-2.5-flash-exp',
                $ai_output_tokens: 100,
                $ai_reasoning_tokens: 200,
            })

            const result = calculateOutputCost(event, gemini25FlashModel)

            // Should include reasoning tokens: (100 + 200) * 0.0000025 = 0.00075
            expectCost(result, 0.00075)
        })
    })

    describe('audio output tokens - modality cost calculation', () => {
        // gpt-4o-audio-preview pricing:
        // - text output: $10/1M ($0.00001/token)
        // - audio output: $80/1M ($0.00008/token)
        const audioModel: ResolvedModelCost = {
            model: 'gpt-4o-audio-preview',
            provider: 'openai',
            cost: {
                prompt_token: 0.0000025,
                completion_token: 0.00001,
                audio: 0.00004,
                audio_output: 0.00008,
            },
        }

        it('bills audio output at the audio_output rate, separate from text', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-4o-audio-preview',
                $ai_output_tokens: 1000, // 200 text + 800 audio
                $ai_audio_output_tokens: 800,
            })

            const result = calculateOutputCost(event, audioModel)

            // Text: (1000 - 800) × 0.00001 = 0.002
            // Audio: 800 × 0.00008 = 0.064
            // Total: 0.066
            expectCost(result, 0.066, 5)
        })

        it('falls back to completion rate when no audio_output rate is defined', () => {
            const modelWithoutAudioOutput: ResolvedModelCost = {
                model: 'some-model',
                provider: 'unknown',
                cost: { prompt_token: 0.000001, completion_token: 0.000002 },
            }
            const event = createAIEvent({
                $ai_provider: 'unknown',
                $ai_model: 'some-model',
                $ai_output_tokens: 1000,
                $ai_audio_output_tokens: 800,
            })

            const result = calculateOutputCost(event, modelWithoutAudioOutput)

            // No separate rate, audio falls back to completion rate.
            // Total stays at 1000 × 0.000002 = 0.002
            expectCost(result, 0.002)
        })

        it('combines audio output with image output for fully multimodal models', () => {
            const multiModalModel: ResolvedModelCost = {
                model: 'multi-modal',
                provider: 'imaginary',
                cost: {
                    prompt_token: 0.000001,
                    completion_token: 0.000002,
                    image_output: 0.00003,
                    audio_output: 0.00004,
                },
            }
            const event = createAIEvent({
                $ai_provider: 'imaginary',
                $ai_model: 'multi-modal',
                $ai_output_tokens: 2000, // 200 text + 800 audio + 1000 image
                $ai_audio_output_tokens: 800,
                $ai_image_output_tokens: 1000,
            })

            const result = calculateOutputCost(event, multiModalModel)

            // Text: 200 × 0.000002 = 0.0004
            // Audio: 800 × 0.00004 = 0.032
            // Image: 1000 × 0.00003 = 0.03
            // Total: 0.0624
            expectCost(result, 0.0624, 5)
        })
    })

    describe('text output tokens type handling', () => {
        const basicModel: ResolvedModelCost = {
            model: 'test-model',
            provider: 'openai',
            cost: { prompt_token: 0.000001, completion_token: 0.000002 },
        }

        it('uses explicit numeric $ai_text_output_tokens when provided', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'test-model',
                $ai_output_tokens: 999, // ignored because text is explicit
                $ai_text_output_tokens: 100,
            })

            // 100 × 0.000002 = 0.0002
            expectCost(calculateOutputCost(event, basicModel), 0.0002)
        })

        it('uses string-encoded $ai_text_output_tokens (some SDKs serialise as strings)', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'test-model',
                $ai_output_tokens: 999,
                $ai_text_output_tokens: '100',
            })

            // bigDecimal accepts strings; "100" × 0.000002 = 0.0002
            expectCost(calculateOutputCost(event, basicModel), 0.0002)
        })

        it('falls back to derivation when $ai_text_output_tokens is null', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'test-model',
                $ai_output_tokens: 100,
                $ai_text_output_tokens: null as any,
            })

            // Derived = 100; cost = 100 × 0.000002 = 0.0002
            expectCost(calculateOutputCost(event, basicModel), 0.0002)
        })

        it('treats unparseable $ai_text_output_tokens as zero rather than poisoning the total', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'test-model',
                $ai_output_tokens: 100,
                $ai_text_output_tokens: 'abc' as any, // garbage from a malformed SDK payload
            })

            // numericProperty returns 0 for non-numeric strings, so text cost is 0.
            // No NaN propagation through bigDecimal.
            expectCost(calculateOutputCost(event, basicModel), 0)
        })
    })
})
