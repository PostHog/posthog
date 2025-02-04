import dotenv from 'dotenv'
import fs from 'fs'
import path from 'path'

dotenv.config()

interface ModelRow {
    model: string
    cost: {
        prompt_token: number
        completion_token: number
    }
}

const supportedProviderList = [
    'openai',
    'anthropic',
    'google',
    'deepseek',
    'perplexity',
    'cohere',
    'mistralai',
    'meta-llama',
]

const main = async () => {
    if (!process.env.OPENROUTER_API_KEY) {
        console.error('OPENROUTER_API_KEY is not set')
        return
    }

    const res = await fetch('https://openrouter.ai/api/v1/models', {
        headers: {
            Authorization: `Bearer ${process.env.OPENROUTER_API_KEY}`,
        },
    })
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
    const baseDir = path.join(process.cwd(), 'src/utils/ai-costs')
    if (!fs.existsSync(baseDir)) {
        fs.mkdirSync(baseDir)
    }

    // Group models by provider
    const providerModels = new Map<string, ModelRow[]>()

    for (const model of models) {
        if (!model?.id || !model?.pricing?.prompt || !model?.pricing?.completion) {
            console.warn('Skipping invalid model:', model)
            continue
        }
        const [provider, ...modelParts] = model.id.split('/')
        if (!supportedProviderList.includes(provider)) {
            continue
        }
        if (!providerModels.has(provider)) {
            providerModels.set(provider, [])
        }

        const modelRow: ModelRow = {
            model: modelParts.join('/'), // Only include the part after the provider
            cost: {
                prompt_token: parseFloat(model.pricing.prompt),
                completion_token: parseFloat(model.pricing.completion),
            },
        }

        providerModels.get(provider)!.push(modelRow)
    }

    // Generate files for each provider
    for (const [provider, models] of providerModels.entries()) {
        if (!fs.existsSync(baseDir)) {
            fs.mkdirSync(baseDir)
        }

        const fileContent = `import type { ModelRow } from './types';\n\nexport const costs: ModelRow[] = ${JSON.stringify(
            models,
            null,
            2
        )};\n`
        fs.writeFileSync(path.join(baseDir, `${provider}.ts`), fileContent)
    }

    // Create types.ts in the base directory
    const typesContent = `export interface ModelRow {
    model: string;
    cost: {
        prompt_token: number;
        completion_token: number;
    };
}`
    fs.writeFileSync(path.join(baseDir, 'types.ts'), typesContent)
}

;(async () => {
    await main()
})().catch((e) => {
    console.error('Error updating AI costs:', e)
    process.exit(1)
})
