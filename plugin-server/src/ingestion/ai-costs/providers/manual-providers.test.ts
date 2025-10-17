import { manualCosts } from './manual-providers'

describe('manualCosts', () => {
    const mistralModels: Array<{
        model: string
        expected: { prompt_token: number; completion_token: number }
    }> = [
        {
            model: 'mistral-medium-3',
            expected: {
                prompt_token: 4e-7,
                completion_token: 0.000002,
            },
        },
        {
            model: 'mistral-large-latest',
            expected: {
                prompt_token: 0.000002,
                completion_token: 0.000006,
            },
        },
        {
            model: 'mistral-large',
            expected: {
                prompt_token: 0.000002,
                completion_token: 0.000006,
            },
        },
        {
            model: 'mistral-small-3.2',
            expected: {
                prompt_token: 0.0000001,
                completion_token: 0.0000003,
            },
        },
    ]

    describe('openrouter/auto model', () => {
        it('is defined with zero costs', () => {
            const openrouterAuto = manualCosts.find((model) => model.model === 'openrouter/auto')

            expect(openrouterAuto).toBeDefined()
            expect(openrouterAuto?.provider).toBe('openrouter')
            expect(openrouterAuto?.cost.prompt_token).toBe(0)
            expect(openrouterAuto?.cost.completion_token).toBe(0)
        })
    })

    describe('mistral models', () => {
        it.each(mistralModels)('has expected costs for $model', ({ model, expected }) => {
            const mistralModel = manualCosts.find((entry) => entry.model === model)

            expect(mistralModel).toBeDefined()
            expect(mistralModel?.provider).toBe('mistral')
            expect(mistralModel?.cost.prompt_token).toBe(expected.prompt_token)
            expect(mistralModel?.cost.completion_token).toBe(expected.completion_token)
        })
    })
})
