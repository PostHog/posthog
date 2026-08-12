import { normalizeLLMProvider } from './llmProviderKeysLogic'

describe('normalizeLLMProvider', () => {
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
})
