import fs from 'fs'
import bigDecimal from 'js-big-decimal'
import path from 'path'

interface ModelRow {
    model: string
    provider?: string
    cost: {
        prompt_token: number
        completion_token: number
        cache_read_token?: number
        cache_write_token?: number
    }
}

interface HeliconeModel {
    provider: string
    model: string
    operator: string
    input_cost_per_1m: number
    output_cost_per_1m: number
    prompt_cache_write_per_1m?: number
    prompt_cache_read_per_1m?: number
    show_in_playground?: boolean
}

const PATH_TO_PROVIDERS = path.join(__dirname, '../providers')

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

    // Group models by provider
    const providerModels = new Map<string, ModelRow[]>()

    for (const model of models) {
        if (!model?.id || !model?.pricing?.prompt || !model?.pricing?.completion) {
            console.warn('Skipping invalid model:', model)
            continue
        }
        const [provider, ...modelParts] = model.id.split('/')

        if (!providerModels.has(provider)) {
            providerModels.set(provider, [])
        }

        // Convert pricing values to numbers before using toFixed(10)
        const promptPrice = new bigDecimal(model.pricing.prompt).getValue()
        const completionPrice = new bigDecimal(model.pricing.completion).getValue()

        // Extract cache costs if available
        let cacheReadCost: number | undefined
        let cacheWriteCost: number | undefined

        if (model.pricing.input_cache_read && parseFloat(model.pricing.input_cache_read) > 0) {
            cacheReadCost = parseFloat(model.pricing.input_cache_read)
        }

        if (model.pricing.input_cache_write && parseFloat(model.pricing.input_cache_write) > 0) {
            cacheWriteCost = parseFloat(model.pricing.input_cache_write)
        }

        const modelRow: ModelRow = {
            model: modelParts.join('/'), // Only include the part after the provider
            cost: {
                prompt_token: parseFloat(promptPrice),
                completion_token: parseFloat(completionPrice),
                ...(cacheReadCost !== undefined && { cache_read_token: cacheReadCost }),
                ...(cacheWriteCost !== undefined && { cache_write_token: cacheWriteCost }),
            },
        }

        providerModels.get(provider)!.push(modelRow)
    }

    const allProviders = Array.from(providerModels.values()).flat()

    // Sort by model name for easier diffs
    allProviders.sort((a, b) => a.model.localeCompare(b.model))

    return allProviders
}

const fetchHeliconeCosts = async (): Promise<ModelRow[]> => {
    // eslint-disable-next-line no-restricted-globals
    const res = await fetch('https://www.helicone.ai/api/llm-costs', {})
    if (!res.ok) {
        throw new Error(`Failed to fetch Helicone models: ${res.status} ${res.statusText}`)
    }

    let responseData: { data: HeliconeModel[] }
    try {
        responseData = await res.json()
    } catch (e) {
        throw new Error('Failed to parse Helicone API response as JSON')
    }

    const data = responseData.data
    console.log(`Fetched ${data.length} models from Helicone`)

    const modelRows: ModelRow[] = []

    for (const heliconeModel of data) {
        // Skip models without required fields
        if (
            !heliconeModel.model ||
            heliconeModel.input_cost_per_1m === undefined ||
            heliconeModel.output_cost_per_1m === undefined
        ) {
            console.warn('Skipping invalid Helicone model:', heliconeModel)
            continue
        }

        const modelRow: ModelRow = {
            model: heliconeModel.model,
            provider:
                heliconeModel.provider.toLowerCase() === 'google' ? 'gemini' : heliconeModel.provider.toLowerCase(),
            cost: {
                // Convert from cost per million to cost per token using bigDecimal for precision
                prompt_token: parseFloat(
                    new bigDecimal(heliconeModel.input_cost_per_1m).divide(new bigDecimal(1_000_000)).getValue()
                ),
                completion_token: parseFloat(
                    new bigDecimal(heliconeModel.output_cost_per_1m).divide(new bigDecimal(1_000_000)).getValue()
                ),
            },
        }

        // Add cache costs if available
        if (heliconeModel.prompt_cache_read_per_1m !== undefined) {
            modelRow.cost.cache_read_token = parseFloat(
                new bigDecimal(heliconeModel.prompt_cache_read_per_1m).divide(new bigDecimal(1_000_000)).getValue()
            )
        }

        if (heliconeModel.prompt_cache_write_per_1m !== undefined) {
            modelRow.cost.cache_write_token = parseFloat(
                new bigDecimal(heliconeModel.prompt_cache_write_per_1m).divide(new bigDecimal(1_000_000)).getValue()
            )
        }

        modelRows.push(modelRow)
    }

    // Sort by model name for easier diffs
    modelRows.sort((a, b) => a.model.localeCompare(b.model))

    return modelRows
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

    console.log('Fetching costs from Helicone...')
    const heliconeCosts = await fetchHeliconeCosts()
    console.log(`Fetched ${heliconeCosts.length} models from Helicone`)

    // Write OpenRouter costs as backup
    fs.writeFileSync(
        path.join(PATH_TO_PROVIDERS, 'backup-llm-provider-costs.json'),
        JSON.stringify(openRouterCosts, null, 2)
    )
    console.log('Wrote OpenRouter costs to backup-llm-provider-costs.json')

    // Write Helicone costs as primary (for future use)
    fs.writeFileSync(path.join(PATH_TO_PROVIDERS, 'llm-provider-costs.json'), JSON.stringify(heliconeCosts, null, 2))
    console.log('Wrote Helicone costs to llm-provider-costs.json')
}

;(async () => {
    await main()
})().catch((e) => {
    console.error('Error updating AI costs:', e)
    process.exit(1)
})
