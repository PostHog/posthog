import dotenv from 'dotenv'
import fs from 'fs'
import bigDecimal from 'js-big-decimal'
import path from 'path'

dotenv.config()

interface ModelRow {
    model: string
    cost: {
        prompt_token: string
        completion_token: string
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

function serializeModels(models: ModelRow[]): string {
    let output = '[\n'
    models.forEach((model, index) => {
        output += '  {\n'
        output += `    model: ${JSON.stringify(model.model)},\n`
        output += '    cost: {\n'
        output += `      prompt_token: ${new bigDecimal(model.cost.prompt_token)
            .round(10)
            .stripTrailingZero()
            .getValue()},\n`
        output += `      completion_token: ${new bigDecimal(model.cost.completion_token)
            .round(10)
            .stripTrailingZero()
            .getValue()}\n`
        output += '    }\n'
        output += '  }'
        output += index < models.length - 1 ? ',\n' : '\n'
    })
    output += ']'
    return output
}

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

        // Convert pricing values to numbers before using toFixed(10)
        const promptPrice = new bigDecimal(model.pricing.prompt).getValue()
        const completionPrice = new bigDecimal(model.pricing.completion).getValue()

        const modelRow: ModelRow = {
            model: modelParts.join('/'), // Only include the part after the provider
            cost: {
                prompt_token: promptPrice,
                completion_token: completionPrice,
            },
        }

        providerModels.get(provider)!.push(modelRow)
    }

    // Generate files for each provider using our custom serializer
    for (const [provider, models] of providerModels.entries()) {
        const fileContent = `import type { ModelRow } from './types';\n\nexport const costs: ModelRow[] = ${serializeModels(
            models
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
