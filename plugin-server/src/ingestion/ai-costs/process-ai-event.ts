import bigDecimal from 'js-big-decimal'

import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { logger } from '../../utils/logger'
import { calculateInputCost } from './input-costs'
import { calculateOutputCost } from './output-costs'
import { backupCostsByModel, primaryCostsList } from './providers'
import { ModelRow } from './providers/types'

// Work around for new gemini models that require special cost calculations
const SPECIAL_COST_MODELS = ['gemini-2.5-pro-preview']

export enum CostModelSource {
    Primary = 'primary',
    Backup = 'backup',
}

interface CostModelResult {
    cost: ModelRow
    source: CostModelSource
}

export const AI_EVENT_TYPES = new Set([
    '$ai_generation',
    '$ai_embedding',
    '$ai_span',
    '$ai_trace',
    '$ai_metric',
    '$ai_feedback',
])

export const normalizeTraceProperties = (event: PluginEvent): PluginEvent => {
    if (!event.properties) {
        return event
    }

    // List of properties that should always be strings
    const keys = ['$ai_trace_id', '$ai_parent_id', '$ai_span_id', '$ai_generation_id']

    for (const key of keys) {
        const value: unknown = event.properties[key]

        if (value === null || value === undefined) {
            continue
        }

        const valueType = typeof value

        if (valueType === 'string' || valueType === 'number' || valueType === 'boolean' || valueType === 'bigint') {
            event.properties[key] = String(value)
        } else {
            event.properties[key] = undefined

            logger.warn(`Unexpected type for trace property ${key}: ${valueType}`)
        }
    }

    return event
}

export const processAiEvent = (event: PluginEvent): PluginEvent => {
    // First, normalize trace properties for ALL AI events
    if (AI_EVENT_TYPES.has(event.event)) {
        event = normalizeTraceProperties(event)
    }

    // Then continue with existing cost processing for generation/embedding
    if ((event.event !== '$ai_generation' && event.event !== '$ai_embedding') || !event.properties) {
        return event
    }

    event = processCost(event)
    event = extractCoreModelParams(event)

    return event
}

const processCost = (event: PluginEvent) => {
    if (!event.properties) {
        return event
    }

    // If we already have input and output costs, we can skip the rest of the logic
    if (event.properties['$ai_input_cost_usd'] && event.properties['$ai_output_cost_usd']) {
        if (!event.properties['$ai_total_cost_usd']) {
            event.properties['$ai_total_cost_usd'] =
                event.properties['$ai_input_cost_usd'] + event.properties['$ai_output_cost_usd']
        }

        return event
    }

    if (!event.properties['$ai_model']) {
        return event
    }

    let model = event.properties['$ai_model']

    if (requireSpecialCost(model)) {
        model = getNewModelName(event.properties)
    }

    const costResult = findCostFromModel(model, event.properties)

    if (!costResult) {
        return event
    }

    const { cost, source } = costResult

    // This is used to track the model that was used for the cost calculation
    event.properties['$ai_model_cost_used'] = cost.model
    event.properties['$ai_cost_model_source'] = source

    event.properties['$ai_input_cost_usd'] = parseFloat(calculateInputCost(event, cost))
    event.properties['$ai_output_cost_usd'] = parseFloat(calculateOutputCost(event, cost))

    event.properties['$ai_total_cost_usd'] = parseFloat(
        bigDecimal.add(event.properties['$ai_input_cost_usd'], event.properties['$ai_output_cost_usd'])
    )

    return event
}

export const extractCoreModelParams = (event: PluginEvent): PluginEvent => {
    if (!event.properties) {
        return event
    }

    const params = event.properties['$ai_model_parameters']

    if (!params) {
        return event
    }

    if (params.temperature !== undefined) {
        event.properties.$ai_temperature = params.temperature
    }

    if (params.stream !== undefined) {
        event.properties.$ai_stream = params.stream
    }

    if (params.max_tokens !== undefined) {
        event.properties.$ai_max_tokens = params.max_tokens
    } else if (params.max_completion_tokens !== undefined) {
        event.properties.$ai_max_tokens = params.max_completion_tokens
    }

    return event
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

const findCostFromModel = (aiModel: string, properties?: Properties): CostModelResult | undefined => {
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

const requireSpecialCost = (aiModel: string): boolean => {
    return SPECIAL_COST_MODELS.some((model) => aiModel.toLowerCase().includes(model.toLowerCase()))
}

const getNewModelName = (properties: Properties): string => {
    const model = properties['$ai_model']

    if (!model) {
        return model
    }

    // Gemini 2.5 Pro Preview has a limit of 200k input tokens before the price changes, we store the other price in the :large suffix
    if (model.toLowerCase().includes('gemini-2.5-pro-preview')) {
        const tokenCountExceeded = properties['$ai_input_tokens'] ? properties['$ai_input_tokens'] > 200000 : false
        return tokenCountExceeded ? 'gemini-2.5-pro-preview:large' : 'gemini-2.5-pro-preview'
    }

    return model
}
