import { PluginEvent } from '@posthog/plugin-scaffold'
import bigDecimal from 'js-big-decimal'

import { logger } from '../../utils/logger'
import { costsByModel } from './providers'
import { ModelRow } from './providers/types'

export const processAiEvent = (event: PluginEvent): PluginEvent => {
    if ((event.event !== '$ai_generation' && event.event !== '$ai_embedding') || !event.properties) {
        return event
    }
    event = processCost(event)
    event = extractCoreModelParams(event)
    return event
}

const calculateInputCost = (event: PluginEvent, cost: ModelRow) => {
    if (!event.properties) {
        return '0'
    }
    if (event.properties['$ai_provider'] && event.properties['$ai_provider'].toLowerCase() === 'openai') {
        const cacheReadTokens = event.properties['$ai_cache_read_input_tokens'] || 0
        const inputTokens = event.properties['$ai_input_tokens'] || 0
        const difference = bigDecimal.subtract(inputTokens, cacheReadTokens)
        const cachedCost = bigDecimal.multiply(bigDecimal.multiply(cost.cost.prompt_token, 0.5), cacheReadTokens)
        const uncachedCost = bigDecimal.multiply(cost.cost.prompt_token, difference)
        return bigDecimal.add(cachedCost, uncachedCost)
    } else if (event.properties['$ai_provider'] && event.properties['$ai_provider'].toLowerCase() === 'anthropic') {
        const cacheReadTokens = event.properties['$ai_cache_read_input_tokens'] || 0
        const cacheWriteTokens = event.properties['$ai_cache_creation_input_tokens'] || 0
        const inputTokens = event.properties['$ai_input_tokens'] || 0
        const writeCost = bigDecimal.multiply(bigDecimal.multiply(cost.cost.prompt_token, 1.25), cacheWriteTokens)
        const cacheReadCost = bigDecimal.multiply(bigDecimal.multiply(cost.cost.prompt_token, 0.1), cacheReadTokens)
        const totalCacheCost = bigDecimal.add(writeCost, cacheReadCost)
        const uncachedCost = bigDecimal.multiply(cost.cost.prompt_token, inputTokens)
        return bigDecimal.add(totalCacheCost, uncachedCost)
    }
    return bigDecimal.multiply(cost.cost.prompt_token, event.properties['$ai_input_tokens'] || 0)
}

const calculateOutputCost = (event: PluginEvent, cost: ModelRow) => {
    if (!event.properties) {
        return '0'
    }
    return bigDecimal.multiply(cost.cost.completion_token, event.properties['$ai_output_tokens'] || 0)
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

    const cost = findCostFromModel(event.properties['$ai_model'])
    if (!cost) {
        return event
    }

    event.properties['$ai_input_cost_usd'] = parseFloat(calculateInputCost(event, cost))
    event.properties['$ai_output_cost_usd'] = parseFloat(calculateOutputCost(event, cost))

    event.properties['$ai_total_cost_usd'] = parseFloat(
        bigDecimal.add(event.properties['$ai_input_cost_usd'], event.properties['$ai_output_cost_usd'])
    )

    return event
}

export const extractCoreModelParams = (event: PluginEvent): PluginEvent => {
    if (!event.properties || !event.properties['$ai_provider'] || !event.properties['$ai_model']) {
        return event
    }
    const provider = event.properties['$ai_provider'].toLowerCase()

    const params = event.properties['$ai_model_parameters']

    if (!params) {
        return event
    }

    if (provider === 'anthropic') {
        if (params.temperature !== undefined) {
            event.properties.$ai_temperature = params.temperature
        }
        if (params.max_tokens !== undefined) {
            event.properties.$ai_max_tokens = params.max_tokens
        }
        if (params.stream !== undefined) {
            event.properties.$ai_stream = params.stream
        }
    } else if (provider === 'openai') {
        if (params.temperature !== undefined) {
            event.properties.$ai_temperature = params.temperature
        }
        if (params.max_completion_tokens !== undefined) {
            event.properties.$ai_max_tokens = params.max_completion_tokens
        }
        if (params.stream !== undefined) {
            event.properties.$ai_stream = params.stream
        }
    } else {
        // Default to openai-like params
        if (params.temperature !== undefined) {
            event.properties.$ai_temperature = params.temperature
        }
        if (params.max_completion_tokens !== undefined) {
            event.properties.$ai_max_tokens = params.max_completion_tokens
        }
        if (params.stream !== undefined) {
            event.properties.$ai_stream = params.stream
        }
    }

    return event
}

const findCostFromModel = (aiModel: string): ModelRow | undefined => {
    // Check if the model is an exact match
    let cost: ModelRow | undefined = costsByModel[aiModel.toLowerCase()]
    // Check if the model is a variant of a known model
    if (!cost) {
        cost = Object.values(costsByModel).find((cost) => aiModel.toLowerCase().includes(cost.model.toLowerCase()))
    }
    // Check if the model is a variant of a known model
    if (!cost) {
        cost = Object.values(costsByModel).find((cost) => aiModel.toLowerCase().includes(cost.model.toLowerCase()))
    }
    if (!cost) {
        logger.warn('🚨', `No cost found for model: ${aiModel}`)
    }
    return cost
}
