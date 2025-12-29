import {
    PROVIDER_ALIASES,
    normalizeProviderKey,
    resolveModelCostForProvider,
    resolveProviderAliases,
} from './provider-matching'
import type { ModelCostByProvider } from './providers/types'

describe('normalizeProviderKey()', () => {
    it('lowercases provider names', () => {
        expect(normalizeProviderKey('OpenAI')).toBe('openai')
        expect(normalizeProviderKey('ANTHROPIC')).toBe('anthropic')
    })

    it('replaces non-alphanumeric characters with hyphens', () => {
        expect(normalizeProviderKey('google_vertex')).toBe('google-vertex')
        expect(normalizeProviderKey('google.ai.studio')).toBe('google-ai-studio')
        expect(normalizeProviderKey('open ai')).toBe('open-ai')
    })

    it('removes leading and trailing hyphens', () => {
        expect(normalizeProviderKey('_provider_')).toBe('provider')
        expect(normalizeProviderKey('.provider.')).toBe('provider')
    })

    it('handles already normalized keys', () => {
        expect(normalizeProviderKey('google-vertex')).toBe('google-vertex')
        expect(normalizeProviderKey('openai')).toBe('openai')
    })
})

describe('resolveProviderAliases()', () => {
    describe('anthropic aliases', () => {
        it('resolves "claude" to "anthropic"', () => {
            expect(resolveProviderAliases('claude')).toBe('anthropic')
        })

        it('resolves "anthropic-claude" to "anthropic"', () => {
            expect(resolveProviderAliases('anthropic-claude')).toBe('anthropic')
        })

        it('resolves "CLAUDE" (uppercase) to "anthropic"', () => {
            expect(resolveProviderAliases('CLAUDE')).toBe('anthropic')
        })
    })

    describe('openai aliases', () => {
        it('resolves "oai" to "openai"', () => {
            expect(resolveProviderAliases('oai')).toBe('openai')
        })

        it('resolves "openai-api" to "openai"', () => {
            expect(resolveProviderAliases('openai-api')).toBe('openai')
        })

        it('resolves "open-ai" to "openai"', () => {
            expect(resolveProviderAliases('open-ai')).toBe('openai')
        })
    })

    describe('google aliases', () => {
        it('resolves "google" to "google-ai-studio"', () => {
            expect(resolveProviderAliases('google')).toBe('google-ai-studio')
        })

        it('resolves "gemini" to "google-ai-studio"', () => {
            expect(resolveProviderAliases('gemini')).toBe('google-ai-studio')
        })

        it('resolves "google-gemini" to "google-ai-studio"', () => {
            expect(resolveProviderAliases('google-gemini')).toBe('google-ai-studio')
        })

        it('resolves "google-ai" to "google-ai-studio"', () => {
            expect(resolveProviderAliases('google-ai')).toBe('google-ai-studio')
        })

        it('resolves "vertex" to "google-vertex"', () => {
            expect(resolveProviderAliases('vertex')).toBe('google-vertex')
        })

        it('resolves "vertex-ai" to "google-vertex"', () => {
            expect(resolveProviderAliases('vertex-ai')).toBe('google-vertex')
        })

        it('resolves "vertex-us" to "google-vertex-us"', () => {
            expect(resolveProviderAliases('vertex-us')).toBe('google-vertex-us')
        })

        it('resolves "vertex-europe" to "google-vertex-europe"', () => {
            expect(resolveProviderAliases('vertex-europe')).toBe('google-vertex-europe')
        })

        it('resolves "vertex-global" to "google-vertex-global"', () => {
            expect(resolveProviderAliases('vertex-global')).toBe('google-vertex-global')
        })
    })

    describe('xai aliases', () => {
        it('resolves "grok" to "xai"', () => {
            expect(resolveProviderAliases('grok')).toBe('xai')
        })

        it('resolves "x-ai" to "xai"', () => {
            expect(resolveProviderAliases('x-ai')).toBe('xai')
        })

        it('resolves "grok-fast" to "xai-fast"', () => {
            expect(resolveProviderAliases('grok-fast')).toBe('xai-fast')
        })

        it('resolves "xai-turbo" to "xai-fast"', () => {
            expect(resolveProviderAliases('xai-turbo')).toBe('xai-fast')
        })
    })

    describe('openrouter aliases', () => {
        it('resolves "openrouter" to "default"', () => {
            expect(resolveProviderAliases('openrouter')).toBe('default')
        })

        it('resolves "or" to "default"', () => {
            expect(resolveProviderAliases('or')).toBe('default')
        })
    })

    describe('other provider aliases', () => {
        it('resolves "amazon" to "amazon-bedrock"', () => {
            expect(resolveProviderAliases('amazon')).toBe('amazon-bedrock')
        })

        it('resolves "aws" to "amazon-bedrock"', () => {
            expect(resolveProviderAliases('aws')).toBe('amazon-bedrock')
        })

        it('resolves "bedrock" to "amazon-bedrock"', () => {
            expect(resolveProviderAliases('bedrock')).toBe('amazon-bedrock')
        })

        it('resolves "aws-bedrock" to "amazon-bedrock"', () => {
            expect(resolveProviderAliases('aws-bedrock')).toBe('amazon-bedrock')
        })

        it('resolves "azure-openai" to "azure"', () => {
            expect(resolveProviderAliases('azure-openai')).toBe('azure')
        })

        it('resolves "azure-ai" to "azure"', () => {
            expect(resolveProviderAliases('azure-ai')).toBe('azure')
        })

        it('resolves "cohere-ai" to "cohere"', () => {
            expect(resolveProviderAliases('cohere-ai')).toBe('cohere')
        })

        it('resolves "mistralai" to "mistral"', () => {
            expect(resolveProviderAliases('mistralai')).toBe('mistral')
        })

        it('resolves "mistral-ai" to "mistral"', () => {
            expect(resolveProviderAliases('mistral-ai')).toBe('mistral')
        })

        it('resolves "deep-seek" to "deepseek"', () => {
            expect(resolveProviderAliases('deep-seek')).toBe('deepseek')
        })

        it('resolves "fireworks-ai" to "fireworks"', () => {
            expect(resolveProviderAliases('fireworks-ai')).toBe('fireworks')
        })

        it('resolves "groq-cloud" to "groq"', () => {
            expect(resolveProviderAliases('groq-cloud')).toBe('groq')
        })

        it('resolves "perplexity-ai" to "perplexity"', () => {
            expect(resolveProviderAliases('perplexity-ai')).toBe('perplexity')
        })

        it('resolves "pplx" to "perplexity"', () => {
            expect(resolveProviderAliases('pplx')).toBe('perplexity')
        })

        it('resolves "cloudflare-workers" to "cloudflare"', () => {
            expect(resolveProviderAliases('cloudflare-workers')).toBe('cloudflare')
        })

        it('resolves "cf-workers" to "cloudflare"', () => {
            expect(resolveProviderAliases('cf-workers')).toBe('cloudflare')
        })
    })

    describe('unknown providers', () => {
        it('returns the normalized provider when no alias is found', () => {
            expect(resolveProviderAliases('unknown-provider')).toBe('unknown-provider')
        })

        it('normalizes unknown providers', () => {
            expect(resolveProviderAliases('Custom_Provider')).toBe('custom-provider')
        })
    })

    describe('normalization in alias matching', () => {
        it('matches aliases regardless of casing', () => {
            expect(resolveProviderAliases('CLAUDE')).toBe('anthropic')
            expect(resolveProviderAliases('Claude')).toBe('anthropic')
        })

        it('matches aliases with different separators', () => {
            expect(resolveProviderAliases('open_ai')).toBe('openai')
            expect(resolveProviderAliases('open.ai')).toBe('openai')
        })
    })
})

describe('resolveModelCostForProvider()', () => {
    const createMockCosts = (
        providers: Record<string, { prompt_token: number; completion_token: number }>
    ): ModelCostByProvider => {
        return providers as ModelCostByProvider
    }

    describe('alias resolution', () => {
        it('resolves provider using aliases', () => {
            const costs = createMockCosts({
                anthropic: { prompt_token: 0.000003, completion_token: 0.000015 },
                default: { prompt_token: 0.000004, completion_token: 0.000018 },
            })

            const result = resolveModelCostForProvider(costs, 'claude', 'claude-3-5-sonnet')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('anthropic')
            expect(result!.model).toBe('claude-3-5-sonnet')
            expect(result!.cost.prompt_token).toBe(0.000003)
        })

        it('resolves openai using "oai" alias', () => {
            const costs = createMockCosts({
                openai: { prompt_token: 0.00003, completion_token: 0.00006 },
                default: { prompt_token: 0.00004, completion_token: 0.00008 },
            })

            const result = resolveModelCostForProvider(costs, 'oai', 'gpt-4')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('openai')
            expect(result!.cost.prompt_token).toBe(0.00003)
        })

        it('resolves google using "gemini" alias', () => {
            const costs = createMockCosts({
                'google-ai-studio': { prompt_token: 0.00000125, completion_token: 0.00001 },
                default: { prompt_token: 0.0000015, completion_token: 0.000012 },
            })

            const result = resolveModelCostForProvider(costs, 'gemini', 'gemini-2.0-flash')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('google-ai-studio')
        })

        it('resolves openrouter to default', () => {
            const costs = createMockCosts({
                anthropic: { prompt_token: 0.000003, completion_token: 0.000015 },
                default: { prompt_token: 0.000004, completion_token: 0.000018 },
            })

            const result = resolveModelCostForProvider(costs, 'openrouter', 'claude-3-5-sonnet')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('default')
            expect(result!.cost.prompt_token).toBe(0.000004)
        })
    })

    describe('exact matching (backward compatibility)', () => {
        it('matches exact provider key without aliases', () => {
            const costs = createMockCosts({
                fireworks: { prompt_token: 0.0000002, completion_token: 0.0000006 },
                default: { prompt_token: 0.0000004, completion_token: 0.0000008 },
            })

            const result = resolveModelCostForProvider(costs, 'fireworks', 'llama-3-8b')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('fireworks')
        })

        it('matches with case normalization', () => {
            const costs = createMockCosts({
                openai: { prompt_token: 0.00003, completion_token: 0.00006 },
            })

            const result = resolveModelCostForProvider(costs, 'OpenAI', 'gpt-4')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('openai')
        })
    })

    describe('partial matching (backward compatibility)', () => {
        it('matches partial provider keys', () => {
            const costs = createMockCosts({
                'deepinfra-fp8': { prompt_token: 0.0000001, completion_token: 0.0000002 },
                default: { prompt_token: 0.0000004, completion_token: 0.0000008 },
            })

            const result = resolveModelCostForProvider(costs, 'deepinfra', 'llama-3-70b')

            expect(result).toBeDefined()
            // Should match deepinfra-fp8 through partial matching OR deepinfra-base through alias
            expect(result!.provider).toMatch(/deepinfra/)
        })
    })

    describe('fallback behavior', () => {
        it('falls back to default when provider is not found', () => {
            const costs = createMockCosts({
                openai: { prompt_token: 0.00003, completion_token: 0.00006 },
                default: { prompt_token: 0.00004, completion_token: 0.00008 },
            })

            const result = resolveModelCostForProvider(costs, 'unknown-provider', 'some-model')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('default')
            expect(result!.cost.prompt_token).toBe(0.00004)
        })

        it('falls back to default when no provider is specified', () => {
            const costs = createMockCosts({
                openai: { prompt_token: 0.00003, completion_token: 0.00006 },
                default: { prompt_token: 0.00004, completion_token: 0.00008 },
            })

            const result = resolveModelCostForProvider(costs, undefined, 'some-model')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('default')
        })

        it('falls back to first available cost when no default exists', () => {
            const costs = createMockCosts({
                openai: { prompt_token: 0.00003, completion_token: 0.00006 },
            })

            const result = resolveModelCostForProvider(costs, undefined, 'gpt-4')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('openai')
        })

        it('returns undefined when cost model is empty', () => {
            const costs = createMockCosts({})

            const result = resolveModelCostForProvider(costs, 'openai', 'gpt-4')

            expect(result).toBeUndefined()
        })
    })

    describe('model name handling', () => {
        it('includes the correct model name in the result', () => {
            const costs = createMockCosts({
                openai: { prompt_token: 0.00003, completion_token: 0.00006 },
            })

            const result = resolveModelCostForProvider(costs, 'openai', 'gpt-4-turbo')

            expect(result).toBeDefined()
            expect(result!.model).toBe('gpt-4-turbo')
        })
    })

    describe('edge cases', () => {
        it('handles null provider costs', () => {
            const result = resolveModelCostForProvider(null as any, 'openai', 'gpt-4')

            expect(result).toBeUndefined()
        })

        it('handles empty string provider', () => {
            const costs = createMockCosts({
                default: { prompt_token: 0.00004, completion_token: 0.00008 },
            })

            const result = resolveModelCostForProvider(costs, '', 'some-model')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('default')
        })
    })

    describe('candidate iteration order', () => {
        it('tries normalized provider first', () => {
            const costs = createMockCosts({
                'custom-provider': { prompt_token: 0.00001, completion_token: 0.00002 },
                Custom_Provider: { prompt_token: 0.00003, completion_token: 0.00004 },
            })

            const result = resolveModelCostForProvider(costs, 'Custom_Provider', 'some-model')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('custom-provider')
        })

        it('falls back to lowercase if normalized not found', () => {
            const costs = createMockCosts({
                customProvider: { prompt_token: 0.00001, completion_token: 0.00002 },
            })

            const result = resolveModelCostForProvider(costs, 'CustomProvider', 'some-model')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('customProvider')
        })

        it('uses original casing as last resort before partial matching', () => {
            const costs = createMockCosts({
                CustomProvider: { prompt_token: 0.00001, completion_token: 0.00002 },
            })

            const result = resolveModelCostForProvider(costs, 'CustomProvider', 'some-model')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('CustomProvider')
        })
    })

    describe('partial matching edge cases', () => {
        it('finds first partial match when multiple providers contain the search string', () => {
            const costs = createMockCosts({
                'openai-turbo': { prompt_token: 0.00001, completion_token: 0.00002 },
                'openai-standard': { prompt_token: 0.00003, completion_token: 0.00004 },
                'openai-fast': { prompt_token: 0.00005, completion_token: 0.00006 },
            })

            const result = resolveModelCostForProvider(costs, 'openai', 'gpt-4')

            expect(result).toBeDefined()
            expect(result!.provider).toMatch(/openai/)
        })

        it('partial match is case insensitive', () => {
            const costs = createMockCosts({
                'deepinfra-turbo': { prompt_token: 0.00001, completion_token: 0.00002 },
            })

            const result = resolveModelCostForProvider(costs, 'DeepInfra', 'llama-3')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('deepinfra-turbo')
        })

        it('does not partially match when exact match exists', () => {
            const costs = createMockCosts({
                openai: { prompt_token: 0.00001, completion_token: 0.00002 },
                'openai-turbo': { prompt_token: 0.00003, completion_token: 0.00004 },
            })

            const result = resolveModelCostForProvider(costs, 'openai', 'gpt-4')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('openai')
        })
    })

    describe('provider normalization edge cases', () => {
        it('normalizes provider with underscores and dots', () => {
            const costs = createMockCosts({
                'google-ai-studio': { prompt_token: 0.00001, completion_token: 0.00002 },
            })

            const result = resolveModelCostForProvider(costs, 'google.ai_studio', 'gemini-pro')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('google-ai-studio')
        })

        it('handles providers with special characters', () => {
            const costs = createMockCosts({
                'provider-name': { prompt_token: 0.00001, completion_token: 0.00002 },
            })

            const result = resolveModelCostForProvider(costs, 'Provider@Name!', 'some-model')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('provider-name')
        })

        it('handles providers with multiple consecutive special chars', () => {
            const costs = createMockCosts({
                'my-provider': { prompt_token: 0.00001, completion_token: 0.00002 },
            })

            const result = resolveModelCostForProvider(costs, 'my___provider', 'some-model')

            expect(result).toBeDefined()
            expect(result!.provider).toBe('my-provider')
        })
    })
})

describe('PROVIDER_ALIASES completeness', () => {
    it('includes all major LLM provider aliases', () => {
        const majorAliases = [
            'claude', // → anthropic
            'oai', // → openai
            'gemini', // → google-ai-studio
            'vertex', // → google-vertex
            'aws', // → amazon-bedrock
            'azure-openai', // → azure
            'cohere-ai', // → cohere
            'mistralai', // → mistral
            'grok', // → xai
            'deep-seek', // → deepseek
            'fireworks-ai', // → fireworks
            'groq-cloud', // → groq
            'perplexity-ai', // → perplexity
            'cloudflare-workers', // → cloudflare
        ]

        for (const alias of majorAliases) {
            expect(PROVIDER_ALIASES[alias]).toBeDefined()
        }
    })

    it('includes openrouter default mapping', () => {
        expect(PROVIDER_ALIASES['openrouter']).toBe('default')
        expect(PROVIDER_ALIASES['or']).toBe('default')
    })

    it('all aliases are lowercase and normalized', () => {
        for (const [alias, canonical] of Object.entries(PROVIDER_ALIASES)) {
            // Check alias is lowercase (will be normalized during resolution anyway)
            expect(alias).toBe(alias.toLowerCase())

            // Check canonical value is normalized
            expect(canonical).toBe(normalizeProviderKey(canonical))
        }
    })
})
