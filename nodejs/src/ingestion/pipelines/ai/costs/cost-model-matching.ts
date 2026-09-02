import { logger } from '~/common/utils/logger'
import { Properties } from '~/plugin-scaffold'

import { resolveModelCostForProvider, resolveProviderAliases } from './provider-matching'
import { manualCostsByModel, openRouterCostsByModel } from './providers'
import type { ModelCostRow, ResolvedModelCost } from './providers/types'

// Work around for new gemini models that require special cost calculations
const SPECIAL_COST_MODELS = ['gemini-2.5-pro-preview']

export enum CostModelSource {
    OpenRouter = 'openrouter',
    Manual = 'manual',
    Custom = 'custom',
    Passthrough = 'passthrough',
}

export interface CostModelResult {
    cost: ResolvedModelCost
    source: CostModelSource
}

const findManualCost = (model: string): ModelCostRow | undefined => {
    const lowerCaseModel: string = model.toLowerCase()

    const exactMatch: ModelCostRow | undefined = manualCostsByModel[lowerCaseModel]

    if (exactMatch) {
        return exactMatch
    }

    if (lowerCaseModel.includes('/')) {
        const withoutProvider: string = lowerCaseModel.split('/').pop() ?? lowerCaseModel

        return manualCostsByModel[withoutProvider]
    }

    return undefined
}

const resolveBedrockInferenceProfileProvider = (
    model: string,
    providerCosts: ModelCostRow['cost'],
    provider: string | undefined
): string | undefined => {
    if (!provider || resolveProviderAliases(provider) !== 'amazon-bedrock') {
        return provider
    }

    const lowerCaseModel = model.toLowerCase()
    const inferenceProfileArn =
        /^arn:(?:aws|aws-cn|aws-us-gov):bedrock:([a-z0-9-]+):\d{12}:inference-profile\/[^/]+$/.exec(lowerCaseModel)
    const arnProvider = inferenceProfileArn ? `amazon-bedrock-${inferenceProfileArn[1]}` : undefined

    if (arnProvider && providerCosts[arnProvider]) {
        return arnProvider
    }

    const modelId: string = lowerCaseModel.split('/').pop() ?? lowerCaseModel
    const profilePrefix: string = modelId.split('.')[0]
    const profileProviderPrefix = `amazon-bedrock-${profilePrefix}`

    if (providerCosts[profileProviderPrefix]) {
        return profileProviderPrefix
    }

    const regionalProviders = Object.keys(providerCosts).filter(
        (providerKey) => providerKey.startsWith(`${profileProviderPrefix}-`) && providerCosts[providerKey]
    )

    return regionalProviders.length === 1 ? regionalProviders[0] : provider
}

export const findCostFromModel = (model: string, properties: Properties): CostModelResult | undefined => {
    const providerProperty: unknown = properties['$ai_provider']

    const provider: string | undefined = providerProperty ? String(providerProperty).toLowerCase() : undefined

    const manualMatch: ModelCostRow | undefined = findManualCost(model)

    const resolvedManualMatch: ResolvedModelCost | undefined = manualMatch
        ? resolveModelCostForProvider(
              manualMatch.cost,
              resolveBedrockInferenceProfileProvider(model, manualMatch.cost, provider),
              manualMatch.model
          )
        : undefined

    if (resolvedManualMatch) {
        return { cost: resolvedManualMatch, source: CostModelSource.Manual }
    }

    const openRouterMatch: ModelCostRow | undefined = searchModelInCosts(model, openRouterCostsByModel)

    const resolvedOpenRouterMatch: ResolvedModelCost | undefined = openRouterMatch
        ? resolveModelCostForProvider(
              openRouterMatch.cost,
              resolveBedrockInferenceProfileProvider(model, openRouterMatch.cost, provider),
              openRouterMatch.model
          )
        : undefined

    if (resolvedOpenRouterMatch) {
        return { cost: resolvedOpenRouterMatch, source: CostModelSource.OpenRouter }
    }

    logger.warn(`No cost found for model: ${model}${provider ? ` (provider: ${provider})` : ''}`)

    return undefined
}

const normalizeModelForMatching = (model: string): string =>
    model
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')

const getModelMatchVariants = (model: string): string[] => {
    const lowerCaseModel = model.toLowerCase()
    const withoutProvider = lowerCaseModel.includes('/')
        ? (lowerCaseModel.split('/').pop() ?? lowerCaseModel)
        : lowerCaseModel

    const variants = new Set<string>([
        lowerCaseModel,
        normalizeModelForMatching(lowerCaseModel),
        withoutProvider,
        normalizeModelForMatching(withoutProvider),
    ])

    return Array.from(variants).filter((variant) => variant.length > 0)
}

const searchModelInCosts = (model: string, costsDict: Record<string, ModelCostRow>): ModelCostRow | undefined => {
    const lowerCaseModel: string = model.toLowerCase()

    // 1. Exact match keeps the model as-is (for example, `gpt-4` stays `gpt-4`)
    let cost: ModelCostRow | undefined = costsDict[lowerCaseModel]

    if (cost) {
        return cost
    }

    // 2. Longest contained name handles extra suffixes (for example, `gpt-4.1-mini-2025` matches `gpt-4.1-mini`)
    let bestSubMatch: ModelCostRow | undefined = undefined

    let longestMatchLength: number = 0

    const modelVariants: string[] = getModelMatchVariants(model)

    for (const entry of Object.values(costsDict)) {
        const entryVariants = getModelMatchVariants(entry.model)

        for (const entryVariant of entryVariants) {
            for (const modelVariant of modelVariants) {
                if (modelVariant.includes(entryVariant)) {
                    if (entryVariant.length > longestMatchLength) {
                        longestMatchLength = entryVariant.length

                        bestSubMatch = entry
                    }

                    break
                }
            }
        }
    }

    if (bestSubMatch) {
        return bestSubMatch
    }

    // 3. Model inside a known name covers shortened inputs (for example, `gpt-4` matches `gpt-4-turbo`)
    cost = Object.values(costsDict).find((entry) => {
        const entryVariants = getModelMatchVariants(entry.model)

        return entryVariants.some((entryVariant) =>
            modelVariants.some((modelVariant) => entryVariant.includes(modelVariant))
        )
    })

    if (cost) {
        return cost
    }

    return undefined
}

export const requireSpecialCost = (aiModel: string): boolean => {
    const lowerAiModel = aiModel.toLowerCase()

    return SPECIAL_COST_MODELS.some((model) => lowerAiModel.includes(model.toLowerCase()))
}

export function getNewModelName(model: string, inputTokens: unknown): string {
    // Gemini 2.5 Pro Preview has a limit of 200k input tokens before the price changes, we store the other price in the :large suffix
    if (model.toLowerCase().includes('gemini-2.5-pro-preview')) {
        const tokenCountExceeded = inputTokens ? Number(inputTokens) > 200000 : false

        return tokenCountExceeded ? 'gemini-2.5-pro-preview:large' : 'gemini-2.5-pro-preview'
    }

    return model
}
