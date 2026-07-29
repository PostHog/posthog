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
    'grok-fast': 'xai',
    'xai-turbo': 'xai',

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
 * Cross-region inference profiles prefix the model ID with the region the request ran in
 * (`us.anthropic.claude-sonnet-5`). That token is the only signal telling us which regional
 * pricing row applies, so we keep it and use it to pick between provider keys.
 *
 * Each token maps to the region key prefixes to try, in order. `global` is the last resort
 * everywhere because it is the un-regioned list price — a closer stand-in for a missing region
 * than another region's premium would be.
 */
const INFERENCE_PROFILE_REGIONS = new Map<string, string[]>([
    ['us', ['us', 'global']],
    ['eu', ['eu', 'global']],
    ['apac', ['apac', 'ap', 'global']],
    ['global', ['global']],
])

/**
 * Extracts the cross-region inference-profile token from a model string, if present.
 *
 * The token sits after any `provider/` segment (`bedrock/us.anthropic.claude-sonnet-5`) or
 * inference-profile ARN path, so we only look at the part after the last slash.
 *
 * @param model - The raw model name from the event
 * @returns The region token (for example `us`), or undefined for unprefixed models
 */
export const extractInferenceProfileRegion = (model: string): string | undefined => {
    const modelId: string = model.toLowerCase().split('/').pop() ?? ''

    const token: string = modelId.split('.')[0]

    return INFERENCE_PROFILE_REGIONS.has(token) ? token : undefined
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
 * Finds the provider key whose region matches the request's inference profile, for example
 * `amazon-bedrock-us-east-1` for a `us.` profile served by `amazon-bedrock`.
 *
 * Candidates are sorted so the pick stays stable — key order in `llm-costs.json` is regenerated
 * by a scheduled job and must not decide which region we bill at.
 */
const findRegionalProviderMatch = (
    providerCosts: ModelCostByProvider,
    providerSearches: string[],
    region: string,
    findProviderMatch: (providerKey: string) => ResolvedModelCost | undefined
): ResolvedModelCost | undefined => {
    const regionPrefixes: string[] | undefined = INFERENCE_PROFILE_REGIONS.get(region)

    if (!regionPrefixes) {
        return undefined
    }

    const providerKeys: string[] = Object.keys(providerCosts).sort()

    for (const search of providerSearches) {
        for (const regionPrefix of regionPrefixes) {
            const regionKey = `${search}-${regionPrefix}`

            for (const providerKey of providerKeys) {
                // Only match on a key boundary, so `us` never matches `amazon-bedrock-usw`.
                if (providerKey !== regionKey && !providerKey.startsWith(`${regionKey}-`)) {
                    continue
                }

                const match: ResolvedModelCost | undefined = findProviderMatch(providerKey)

                if (match) {
                    return match
                }
            }
        }
    }

    return undefined
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
 * @param region - Inference-profile region token from the model ID (optional), preferred over
 *                 both the un-regioned provider key and the partial-match fallback
 * @returns The resolved model cost, or undefined if no valid cost is found
 */
export const resolveModelCostForProvider = (
    providerCosts: ModelCostByProvider,
    provider: string | undefined,
    model: string,
    region?: string
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
        const canonicalKey: string = resolveProviderAliases(provider)
        const normalizedProvider: string = normalizeProviderKey(provider)

        // Search against the canonical key too so regional-only cost records
        // (e.g. `google-ai-studio-global`) still match when the event uses an alias like `gemini`.
        const providerSearches: string[] =
            canonicalKey === normalizedProvider ? [normalizedProvider] : [canonicalKey, normalizedProvider]

        // A region from the model's inference profile is stronger evidence than any of the
        // matches below: without it we would fall through to the partial match and pick whichever
        // regional key happens to come first in the cost model.
        const regionalMatch: ResolvedModelCost | undefined = region
            ? findRegionalProviderMatch(providerCosts, providerSearches, region, findProviderMatch)
            : undefined

        if (regionalMatch) {
            return regionalMatch
        }

        // Try alias resolution first
        const match: ResolvedModelCost | undefined = findProviderMatch(canonicalKey)

        if (match) {
            return match
        }

        // Try provider variations
        const providerCandidates: string[] = [normalizedProvider, provider.toLowerCase(), provider]

        for (const candidate of providerCandidates) {
            const candidateMatch: ResolvedModelCost | undefined = findProviderMatch(candidate)

            if (candidateMatch) {
                return candidateMatch
            }
        }

        for (const search of providerSearches) {
            const partialMatchKey: string | undefined = Object.keys(providerCosts).find((key: string) =>
                key.includes(search)
            )

            if (partialMatchKey) {
                const partialMatch: ResolvedModelCost | undefined = findProviderMatch(partialMatchKey)

                if (partialMatch) {
                    return partialMatch
                }
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
