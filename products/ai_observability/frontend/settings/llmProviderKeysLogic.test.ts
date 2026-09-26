import { normalizeLLMProvider, normalizeSystemOneBaseUrlForComparison, toLLMProvider } from './llmProviderKeysLogic'

describe('llmProviderKeysLogic', () => {
    it.each([
        ['google', 'gemini'],
        ['google-ai-studio', 'gemini'],
        ['azure_openai', 'azure_openai'],
        ['azure-openai', 'azure_openai'],
        ['azure openai', 'azure_openai'],
        ['together', 'together_ai'],
        ['together ai', 'together_ai'],
        ['together-ai', 'together_ai'],
        ['mini max', 'minimax'],
        ['mini-max', 'minimax'],
        ['minimax', 'minimax'],
        ['zeabur ai hub', 'zeabur'],
        ['zeabur-ai-hub', 'zeabur'],
        ['zeabur', 'zeabur'],
        ['openai', 'openai'],
        ['System One', 'system_one'],
        ['system_one', 'system_one'],
    ])('maps %s to %s', (input, expected) => {
        expect(normalizeLLMProvider(input)).toBe(expected)
    })

    it('trims whitespace before matching aliases', () => {
        expect(normalizeLLMProvider('  mini max  ')).toBe('minimax')
    })

    it('returns null for undefined and unknown providers', () => {
        expect(normalizeLLMProvider(undefined)).toBeNull()
        expect(normalizeLLMProvider('unknown-provider')).toBeNull()
    })

    it('recognizes the System One display name in model pickers', () => {
        expect(toLLMProvider('System One')).toBe('system_one')
    })

    it.each([
        ['https://DECISIONS.example.com/v1/', 'https://decisions.example.com/v1'],
        ['https://decisions.example.com:443/v1', 'https://decisions.example.com/v1'],
    ])('treats %s as the same endpoint as %s', (input, expected) => {
        expect(normalizeSystemOneBaseUrlForComparison(input)).toBe(expected)
    })
})
