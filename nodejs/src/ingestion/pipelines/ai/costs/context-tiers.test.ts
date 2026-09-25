import { applyContextTier, promptTokensForTier } from './context-tiers'
import type { ContextLengthTier, ResolvedModelCost } from './providers/types'
import { createAIEvent } from './test-helpers'

const modelCost = (tiers?: ContextLengthTier[]): ResolvedModelCost => ({
    model: 'test-model',
    provider: 'test',
    cost: {
        prompt_token: 0.000002,
        completion_token: 0.00001,
        cache_read_token: 2e-7,
        context_tiers: tiers,
    },
})

const LONG_CONTEXT: ContextLengthTier = {
    min_input_tokens: 272000,
    prompt_token: 0.000004,
    completion_token: 0.00002,
}

describe('context tiers', () => {
    describe('applyContextTier()', () => {
        it.each([
            { description: 'below the threshold', promptTokens: 271999, expected: 0.000002 },
            { description: 'exactly at the threshold', promptTokens: 272000, expected: 0.000002 },
            { description: 'above the threshold', promptTokens: 272001, expected: 0.000004 },
        ])('prices a prompt $description', ({ promptTokens, expected }) => {
            const tiered = applyContextTier(modelCost([LONG_CONTEXT]), promptTokens)

            expect(tiered.cost.prompt_token).toBe(expected)
        })

        it('moves the output rate with the input rate', () => {
            const tiered = applyContextTier(modelCost([LONG_CONTEXT]), 500000)

            expect(tiered.cost.completion_token).toBe(0.00002)
        })

        it('keeps a rate the tier does not name', () => {
            const tiered = applyContextTier(modelCost([LONG_CONTEXT]), 500000)

            expect(tiered.cost.cache_read_token).toBe(2e-7)
        })

        it('picks the highest tier the prompt passes, whatever order they are listed in', () => {
            const tiers: ContextLengthTier[] = [
                { min_input_tokens: 1000000, prompt_token: 0.000008 },
                { min_input_tokens: 272000, prompt_token: 0.000004 },
            ]

            expect(applyContextTier(modelCost(tiers), 1500000).cost.prompt_token).toBe(0.000008)
            expect(applyContextTier(modelCost(tiers), 300000).cost.prompt_token).toBe(0.000004)
        })

        it('leaves a model without tiers untouched', () => {
            const cost = modelCost()

            expect(applyContextTier(cost, 1000000)).toBe(cost)
        })
    })

    describe('promptTokensForTier()', () => {
        it('reads the reported input tokens when they already cover the cache', () => {
            const event = createAIEvent({
                $ai_provider: 'openai',
                $ai_model: 'gpt-4.1',
                $ai_input_tokens: 300000,
                $ai_cache_read_input_tokens: 250000,
            })

            expect(promptTokensForTier(event)).toBe(300000)
        })

        it('adds the cache pools back when the provider reports input exclusive of them', () => {
            // Anthropic bills a 300K prompt that was mostly cached as 30K input plus
            // the two cache pools, so the threshold has to see the whole prompt.
            const event = createAIEvent({
                $ai_provider: 'anthropic',
                $ai_model: 'claude-sonnet-4',
                $ai_input_tokens: 30000,
                $ai_cache_read_input_tokens: 250000,
                $ai_cache_creation_input_tokens: 20000,
            })

            expect(promptTokensForTier(event)).toBe(300000)
        })

        it('sums the cache write breakdown when only that is reported', () => {
            const event = createAIEvent({
                $ai_provider: 'anthropic',
                $ai_model: 'claude-sonnet-4',
                $ai_input_tokens: 30000,
                $ai_cache_read_input_tokens: 250000,
                $ai_cache_creation_5m_input_tokens: 15000,
                $ai_cache_creation_1h_input_tokens: 5000,
            })

            expect(promptTokensForTier(event)).toBe(300000)
        })
    })
})
