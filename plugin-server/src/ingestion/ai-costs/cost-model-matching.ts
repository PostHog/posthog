import { Properties } from '@posthog/plugin-scaffold'

import { logger } from '../../utils/logger'
import { backupCostsByModel, primaryCostsList } from './providers'
import { ModelRow } from './providers/types'

// Work around for new gemini models that require special cost calculations
const SPECIAL_COST_MODELS = ['gemini-2.5-pro-preview']

export enum CostModelSource {
    Primary = 'primary',
    Backup = 'backup',
    Custom = 'custom',
}

export interface CostModelResult {
    cost: ModelRow
    source: CostModelSource
}

const searchModelInCosts = (aiModel: string, costsDict: Record<string, ModelRow>): ModelRow | undefined => {
    const lowerAiModel = aiModel.toLowerCase()

    // 1. Attempt exact match first
    let cost: ModelRow | undefined = costsDict[lowerAiModel]

    if (cost) {
        return cost
    }

    // 2. Partial match: A known model's name is a substring of aiModel.
    //    e.g., aiModel="gpt-4.1-mini-2025-04-14", known model="gpt-4.1-mini".
    let bestSubMatch: ModelRow | undefined = undefined
    let longestMatchLength = 0

    for (const modelRow of Object.values(costsDict)) {
        const lowerKnownModelName = modelRow.model.toLowerCase()

        if (lowerAiModel.includes(lowerKnownModelName)) {
            if (lowerKnownModelName.length > longestMatchLength) {
                longestMatchLength = lowerKnownModelName.length
                bestSubMatch = modelRow
            }
        }
    }

    if (bestSubMatch) {
        return bestSubMatch
    }

    // 3. Partial match: aiModel is a substring of a known model's name.
    cost = Object.values(costsDict).find((modelRow) => modelRow.model.toLowerCase().includes(lowerAiModel))

    if (cost) {
        return cost
    }

    return undefined
}

export const findCostFromModel = (aiModel: string, properties?: Properties): CostModelResult | undefined => {
    const provider = properties?.['$ai_provider']?.toLowerCase()

    // First: Try primary costs filtered by provider
    if (provider) {
        const providerFilteredCosts = primaryCostsList.filter((row) => row.provider?.toLowerCase() === provider)

        if (providerFilteredCosts.length > 0) {
            // Convert filtered list to dictionary for consistent search logic
            const filteredDict: Record<string, ModelRow> = {}

            for (const cost of providerFilteredCosts) {
                filteredDict[cost.model.toLowerCase()] = cost
            }

            const result = searchModelInCosts(aiModel, filteredDict)

            if (result) {
                return { cost: result, source: CostModelSource.Primary }
            }
        }
    }

    // Second: Fall back to backup costs
    const backupResult = searchModelInCosts(aiModel, backupCostsByModel)

    if (!backupResult) {
        logger.warn(`No cost found for model: ${aiModel}${provider ? ` (provider: ${provider})` : ''}`)
        return undefined
    }

    return { cost: backupResult, source: CostModelSource.Backup }
}

export const requireSpecialCost = (aiModel: string): boolean => {
    const lowerAiModel = aiModel.toLowerCase()
    return SPECIAL_COST_MODELS.some((model) => lowerAiModel.includes(model.toLowerCase()))
}

export const getNewModelName = (properties: Properties): string => {
    const model = properties['$ai_model']

    if (!model) {
        return model
    }

    // Gemini 2.5 Pro Preview has a limit of 200k input tokens before the price changes, we store the other price in the :large suffix
    if (model.toLowerCase().includes('gemini-2.5-pro-preview')) {
        const tokenCountExceeded = properties['$ai_input_tokens']
            ? Number(properties['$ai_input_tokens']) > 200000
            : false
        return tokenCountExceeded ? 'gemini-2.5-pro-preview:large' : 'gemini-2.5-pro-preview'
    }

    return model
}
