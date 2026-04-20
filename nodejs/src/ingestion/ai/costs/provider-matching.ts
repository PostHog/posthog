import type { CanonicalProvider } from './providers/canonical-providers'
import type { ModelCost, ModelCostByProvider, ResolvedModelCost } from './providers/types'

/**
 * Provider aliases allow incoming provider names to map to canonical provider keys
 * used in the cost model.
 *
 * Format: { "alias": "canonical-provider-key" }
 *
 * When a provider name comes in, we check if it matches any alias and resolve it
 * to the canonical key before attempting to find costs.
 *
 * TypeScript enforces that all values are valid CanonicalProvider types.
 */
export const PROVIDER_ALIASES: Record<string, CanonicalProvider> = {
    // Anthropic / Claude
    claude: 'anthropic',
    'anthropic-claude': 'anthropic',

    // OpenAI
    oai: 'openai',
    'openai-api': 'openai',
    'open-ai': 'openai',

    // Google / Gemini
    google: 'google-ai-studio',
    gemini: 'google-ai-studio',
    'google-gemini': 'google-ai-studio',
    'google-ai': 'google-ai-studio',
    vertex: 'google-vertex',
    'vertex-ai': 'google-vertex',
    'vertex-us': 'google-vertex-us',
    'vertex-europe': 'google-vertex-europe',
    'vertex-global': 'google-vertex-global',

    // Amazon
    amazon: 'amazon-bedrock',
    bedrock: 'amazon-bedrock',
    aws: 'amazon-bedrock',
    'aws-bedrock': 'amazon-bedrock',

    // Azure
    'azure-openai': 'azure',
    'azure-ai': 'azure',

    // Cohere
    'cohere-ai': 'cohere',

    // Mistral
    mistralai: 'mistral',
    'mistral-ai': 'mistral',

    // xAI / Grok
    grok: 'xai',
    'x-ai': 'xai',
    'grok-fast': 'xai-fast',
    'xai-turbo': 'xai-fast',

    // DeepSeek
    'deep-seek': 'deepseek',

    // Fireworks
    'fireworks-ai': 'fireworks',

    // Groq
    'groq-cloud': 'groq',

    // Perplexity
    'perplexity-ai': 'perplexity',
    pplx: 'perplexity',

    // Cloudflare
    'cloudflare-workers': 'cloudflare',
    'cf-workers': 'cloudflare',

    // OpenRouter (maps to default pricing)
    openrouter: 'default',
    or: 'default',
}

/**
 * Normalizes a provider key by lowercasing and replacing non-alphanumeric characters
 * with hyphens.
 */
export const normalizeProviderKey = (provider: string): string =>
    provider
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')

/**
 * Resolves a provider name to a canonical provider key using the alias map.
 *
 * @param provider - The provider name from the event
 * @returns The canonical provider key, or the normalized provider name if no alias exists
 */
export const resolveProviderAliases = (provider: string): string => {
    const normalizedProvider = normalizeProviderKey(provider)

    return PROVIDER_ALIASES[normalizedProvider] ?? normalizedProvider
}

/**
 * Attempts to find a matching provider in the cost model.
 *
 * First checks for exact matches using alias resolution, then falls back to
 * partial matching, and finally to the default provider.
 *
 * @param providerCosts - The cost model with provider-specific pricing
 * @param provider - The provider name from the event (optional)
 * @param model - The model name for the resolved cost
 * @returns The resolved model cost, or undefined if no valid cost is found
 */
export const resolveModelCostForProvider = (
    providerCosts: ModelCostByProvider,
    provider: string | undefined,
    model: string
): ResolvedModelCost | undefined => {
    if (!providerCosts || Object.keys(providerCosts).length === 0) {
        return undefined
    }

    const findProviderMatch = (providerKey: string): ResolvedModelCost | undefined => {
        const cost: ModelCost | undefined = providerCosts[providerKey]

        if (!cost) {
            return undefined
        }

        return {
            model,
            provider: providerKey,
            cost,
        }
    }

    if (provider) {
        // Try alias resolution first
        const canonicalKey: string = resolveProviderAliases(provider)
        const match: ResolvedModelCost | undefined = findProviderMatch(canonicalKey)

        if (match) {
            return match
        }

        // Try provider variations
        const normalizedProvider: string = normalizeProviderKey(provider)

        const providerCandidates: string[] = [normalizedProvider, provider.toLowerCase(), provider]

        for (const candidate of providerCandidates) {
            const candidateMatch: ResolvedModelCost | undefined = findProviderMatch(candidate)

            if (candidateMatch) {
                return candidateMatch
            }
        }

        // Try partial matching
        const partialMatchKey: string | undefined = Object.keys(providerCosts).find((key: string) =>
            key.includes(normalizedProvider)
        )

        if (partialMatchKey) {
            const partialMatch: ResolvedModelCost | undefined = findProviderMatch(partialMatchKey)

            if (partialMatch) {
                return partialMatch
            }
        }
    }

    // Fall back to default provider
    const defaultMatch: ResolvedModelCost | undefined = findProviderMatch('default')

    if (defaultMatch) {
        return defaultMatch
    }

    // Fall back to first available cost
    const firstEntry = Object.entries(providerCosts).find(([, value]) => value !== undefined)

    if (!firstEntry) {
        return undefined
    }

    const [firstProvider, firstCost] = firstEntry

    if (!firstCost) {
        return undefined
    }

    return {
        model,
        provider: firstProvider,
        cost: firstCost,
    }
}
