import fs from 'fs'
import bigDecimal from 'js-big-decimal'
import path from 'path'

interface ModelRow {
    model: string
    cost: {
        prompt_token: number
        completion_token: number
        cache_read_token?: number
        cache_write_token?: number
    }
}

const PATH_TO_PROVIDERS = path.join(__dirname, '../providers')

const main = async () => {
    // eslint-disable-next-line no-restricted-globals
    const res = await fetch('https://openrouter.ai/api/v1/models', {})
    if (!res.ok) {
        throw new Error(`Failed to fetch models: ${res.status} ${res.statusText}`)
    }
    let data
    try {
        data = await res.json()
    } catch (e) {
        throw new Error('Failed to parse API response as JSON')
    }
    console.log(data.data)
    const models = data.data

    // Create main directory
    if (!fs.existsSync(PATH_TO_PROVIDERS)) {
        fs.mkdirSync(PATH_TO_PROVIDERS)
    }

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

    // Write everything as a json file
    fs.writeFileSync(path.join(PATH_TO_PROVIDERS, 'generated-providers.json'), JSON.stringify(allProviders, null, 2))
}

;(async () => {
    await main()
})().catch((e) => {
    console.error('Error updating AI costs:', e)
    process.exit(1)
})
