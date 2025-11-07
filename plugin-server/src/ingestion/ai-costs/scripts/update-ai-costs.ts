import fs from 'fs'
import bigDecimal from 'js-big-decimal'
import path from 'path'

interface ModelCost {
    prompt_token: number
    completion_token: number
    cache_read_token?: number
    cache_write_token?: number
    request?: number
    web_search?: number
    image?: number
    image_output?: number
    audio?: number
    input_audio_cache?: number
    internal_reasoning?: number
}

interface ModelRow {
    model: string
    cost: Record<string, ModelCost>
}

const PATH_TO_PROVIDERS = path.join(__dirname, '../providers')
const OPENROUTER_COSTS_FILENAME = 'llm-costs.json'

const parsePricingNumber = (value: unknown): number | undefined => {
    if (value === null || value === undefined) {
        return undefined
    }

    const valueAsString = typeof value === 'number' ? value.toString() : value
    if (typeof valueAsString !== 'string') {
        return undefined
    }

    try {
        const decimalValue = new bigDecimal(valueAsString).getValue()
        const parsed = parseFloat(decimalValue)
        if (Number.isNaN(parsed)) {
            return undefined
        }

        if (parsed < 0) {
            return 0
        }

        return parsed
    } catch (error) {
        console.warn('Failed to parse pricing value:', value, error)
        return undefined
    }
}

const buildModelCost = (pricing: Record<string, unknown> | undefined): ModelCost | null => {
    if (!pricing) {
        return null
    }

    const promptToken = parsePricingNumber(pricing.prompt)
    const completionToken = parsePricingNumber(pricing.completion)

    if (promptToken === undefined || completionToken === undefined) {
        return null
    }

    const cost: ModelCost = {
        prompt_token: promptToken,
        completion_token: completionToken,
    }

    const optionalPricingFields: Array<[keyof ModelCost, string]> = [
        ['cache_read_token', 'input_cache_read'],
        ['cache_write_token', 'input_cache_write'],
        ['request', 'request'],
        ['web_search', 'web_search'],
        ['image', 'image'],
        ['image_output', 'image_output'],
        ['audio', 'audio'],
        ['input_audio_cache', 'input_audio_cache'],
        ['internal_reasoning', 'internal_reasoning'],
    ]

    for (const [targetField, sourceField] of optionalPricingFields) {
        const parsedValue = parsePricingNumber(pricing[sourceField])
        if (parsedValue !== undefined && parsedValue !== 0) {
            cost[targetField] = parsedValue
        }
    }

    return cost
}

const normalizeProviderKey = (endpoint: { tag?: string; provider_name?: string; name?: string }): string => {
    const rawKey = endpoint.tag || endpoint.provider_name || endpoint.name || 'unknown'
    return rawKey
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
}

const fetchOpenRouterCosts = async (): Promise<ModelRow[]> => {
    // eslint-disable-next-line no-restricted-globals
    const res = await fetch('https://openrouter.ai/api/v1/models', {})
    if (!res.ok) {
        throw new Error(`Failed to fetch OpenRouter models: ${res.status} ${res.statusText}`)
    }

    let data
    try {
        data = await res.json()
    } catch (e) {
        throw new Error('Failed to parse OpenRouter API response as JSON')
    }

    console.log('OpenRouter models:', data.data.length)
    const models = data.data

    const allModels: ModelRow[] = []

    for (const [modelIndex, model] of models.entries()) {
        if (!model?.id) {
            console.warn('Skipping model without id:', model)
            continue
        }

        const defaultCost = buildModelCost(model.pricing)
        if (!defaultCost) {
            console.warn('Skipping model without valid pricing:', model.id)
            continue
        }

        const costs: Record<string, ModelCost> = {
            default: defaultCost,
        }

        const encodedModelId = model.id
            .split('/')
            .map((segment: string) => encodeURIComponent(segment))
            .join('/')

        try {
            console.log(`Fetching endpoint pricing for ${modelIndex + 1}/${models.length} ${model.id}...`)
            // eslint-disable-next-line no-restricted-globals
            const endpointRes = await fetch(`https://openrouter.ai/api/v1/models/${encodedModelId}/endpoints`, {})
            if (!endpointRes.ok) {
                console.warn(
                    `Failed to fetch endpoint pricing for ${model.id}: ${endpointRes.status} ${endpointRes.statusText}`
                )
            } else {
                let endpointsPayload
                try {
                    endpointsPayload = await endpointRes.json()
                } catch (parseError) {
                    console.warn('Failed to parse endpoint pricing payload for model:', model.id, parseError)
                }

                const endpoints = endpointsPayload?.data?.endpoints ?? []
                for (const endpoint of endpoints) {
                    const endpointCost = buildModelCost(endpoint?.pricing)
                    if (!endpointCost) {
                        continue
                    }

                    const providerKey = normalizeProviderKey(endpoint)
                    const safeProviderKey =
                        providerKey && providerKey !== 'default'
                            ? providerKey
                            : `provider-${endpoint.provider_name ?? 'unknown'}`
                    costs[safeProviderKey] = endpointCost
                }
            }
        } catch (error) {
            console.warn('Error fetching endpoint pricing for model:', model.id, error)
        }

        allModels.push({
            model: model.id,
            cost: costs,
        })
    }

    allModels.sort((a, b) => a.model.localeCompare(b.model))

    return allModels
}

const sortProviderCosts = (models: ModelRow[]): ModelRow[] => {
    return models.map((model) => {
        const sortedCost: Record<string, ModelCost> = {}

        // Get all provider keys and sort them
        const providerKeys = Object.keys(model.cost)
        const otherProviders = providerKeys.filter((key) => key !== 'default').sort()

        // Always put 'default' first, then add the rest alphabetically
        if (model.cost.default) {
            sortedCost.default = model.cost.default
        }

        for (const provider of otherProviders) {
            sortedCost[provider] = model.cost[provider]
        }

        return {
            ...model,
            cost: sortedCost,
        }
    })
}

const generateCanonicalProviders = (models: ModelRow[]): void => {
    // Extract all unique provider keys from the cost data
    const providerSet = new Set<string>()

    for (const model of models) {
        for (const providerKey of Object.keys(model.cost)) {
            providerSet.add(providerKey)
        }
    }

    // Sort deterministically: default first, then alphabetically
    const allProviders = Array.from(providerSet)
    const otherProviders = allProviders.filter((p) => p !== 'default').sort()
    const providers = allProviders.includes('default') ? ['default', ...otherProviders] : otherProviders

    // Generate TypeScript file content
    const now = new Date()
    const timestamp = `${now.toISOString().split('.')[0].replace('T', ' ')} UTC`
    const typeUnion = providers.map((p) => `    | '${p}'`).join('\n')

    const fileContent = `// Auto-generated from OpenRouter API - Do not edit manually
// Generated at: ${timestamp}

export type CanonicalProvider =
${typeUnion}
`

    // Write the file
    const filePath = path.join(PATH_TO_PROVIDERS, 'canonical-providers.ts')
    fs.writeFileSync(filePath, fileContent)
    console.log(`Generated canonical-providers.ts with ${providers.length} provider types`)
}

const main = async () => {
    // Create main directory if it doesn't exist
    if (!fs.existsSync(PATH_TO_PROVIDERS)) {
        fs.mkdirSync(PATH_TO_PROVIDERS)
    }

    // Fetch costs from both providers
    console.log('Fetching costs from OpenRouter...')
    const openRouterCosts = await fetchOpenRouterCosts()
    console.log(`Fetched ${openRouterCosts.length} models from OpenRouter`)

    // Sort provider costs deterministically (default first, then alphabetically)
    const sortedCosts = sortProviderCosts(openRouterCosts)

    // Write OpenRouter costs as backup
    fs.writeFileSync(path.join(PATH_TO_PROVIDERS, OPENROUTER_COSTS_FILENAME), JSON.stringify(sortedCosts, null, 4))
    console.log(`Wrote OpenRouter costs to ${OPENROUTER_COSTS_FILENAME}`)

    // Generate canonical providers TypeScript file
    generateCanonicalProviders(sortedCosts)
}

;(async () => {
    await main()
})().catch((e) => {
    console.error('Error updating AI costs:', e)
    process.exit(1)
})
