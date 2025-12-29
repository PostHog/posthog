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
                cache_read_token: 0.000000625,
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
})
