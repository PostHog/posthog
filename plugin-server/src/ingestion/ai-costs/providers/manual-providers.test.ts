import { manualCosts } from './manual-providers'

describe('manualCosts', () => {
    describe('openrouter/auto model', () => {
        it('is defined with zero costs', () => {
            const openrouterAuto = manualCosts.find((model) => model.model === 'openrouter/auto')

            expect(openrouterAuto).toBeDefined()
            expect(openrouterAuto?.provider).toBe('openrouter')
            expect(openrouterAuto?.cost.prompt_token).toBe(0)
            expect(openrouterAuto?.cost.completion_token).toBe(0)
        })
    })
})
