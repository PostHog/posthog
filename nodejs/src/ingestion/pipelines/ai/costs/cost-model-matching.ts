import { logger } from '~/common/utils/logger'
import { Properties } from '~/plugin-scaffold'

import { resolveModelCostForProvider, resolveProviderAliases } from './provider-matching'
import { manualCostsByModel, openRouterCostsByModel } from './providers'
import { openAILongContextModels } from './providers/manual-providers'
import type { ModelCostRow, ResolvedModelCost } from './providers/types'

// A prompt above `inputTokenThreshold` is billed at the rates of the manual `<model>:large` row.
interface LongContextPricing {
    model: string
    inputTokenThreshold: number
    // The provider that publishes the `:large` rates. Other routes stay on their flat rate,
    // because their long-context rates are not known.
    provider?: string
}

const LONG_CONTEXT_PRICING: LongContextPricing[] = [
    { model: 'gemini-2.5-pro-preview', inputTokenThreshold: 200000 },
    // OpenAI: "Short context: ≤272K input tokens. Long context: >272K input tokens."
    ...openAILongContextModels.map((model) => ({ model, inputTokenThreshold: 272000, provider: 'openai' })),
]

const escapeRegExp = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// The name must end at the model or at a dated snapshot suffix (`-2026-03-05`, `-0514`).
// A longer name such as `gpt-5.4-mini`, `gpt-6-sol-pro` or `gemini-2.5-pro-preview-tts`
// is a different model with its own price, so it must not take this model's long-context rates.
const LONG_CONTEXT_PRICING_PATTERNS: [RegExp, LongContextPricing][] = LONG_CONTEXT_PRICING.map((pricing) => [
    new RegExp(`(?:^|/)${escapeRegExp(pricing.model)}(?:-\\d[\\d-]*)?$`),
    pricing,
])

const findLongContextPricing = (aiModel: string): LongContextPricing | undefined => {
    const lowerAiModel = aiModel.toLowerCase()

    return LONG_CONTEXT_PRICING_PATTERNS.find(([pattern]) => pattern.test(lowerAiModel))?.[1]
}

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

const getAiProvider = (properties: Properties): string | undefined => {
    const provider: unknown = properties['$ai_provider']

    return provider ? String(provider).toLowerCase() : undefined
}

// $ai_service_tier is the explicit served-tier signal: its writers (the ai-gateway, SDK
// versions that adopted it) assert the tier the provider reported serving, on success and
// error events alike. $ai_model_parameters.service_tier never prices: released SDKs wrote
// the requested tier there, and a request can be refused.
const getServedServiceTier = (properties: Properties): unknown => properties['$ai_service_tier']

export const findCostFromModel = (model: string, properties: Properties): CostModelResult | undefined => {
    const provider = getAiProvider(properties)
    const serviceTier = getServedServiceTier(properties)

    const manualMatch: ModelCostRow | undefined = findManualCost(model)

    const resolvedManualMatch: ResolvedModelCost | undefined = manualMatch
        ? resolveModelCostForProvider(
              manualMatch.cost,
              resolveBedrockInferenceProfileProvider(model, manualMatch.cost, provider),
              manualMatch.model,
              serviceTier
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
              openRouterMatch.model,
              serviceTier
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

export const requireSpecialCost = (aiModel: string): boolean => findLongContextPricing(aiModel) !== undefined

export function getNewModelName(model: string, inputTokens: unknown, provider?: unknown): string {
    const pricing = findLongContextPricing(model)

    if (!pricing) {
        return model
    }

    if (pricing.provider && (typeof provider !== 'string' || resolveProviderAliases(provider) !== pricing.provider)) {
        return model
    }

    const tokenCountExceeded = inputTokens ? Number(inputTokens) > pricing.inputTokenThreshold : false

    return tokenCountExceeded ? `${pricing.model}:large` : model
}
