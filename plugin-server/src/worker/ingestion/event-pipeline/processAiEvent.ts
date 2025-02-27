import { PluginEvent } from '@posthog/plugin-scaffold'
import bigDecimal from 'js-big-decimal'

import { costs } from '../../../utils/ai-costs'
import { ModelRow } from '../../../utils/ai-costs/types'

export const processAiEvent = (event: PluginEvent): PluginEvent => {
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

    const cost = findCostFromModel(event.properties['$ai_model'])
    if (!cost) {
        return event
    }

    event.properties['$ai_input_cost_usd'] = parseFloat(
        bigDecimal.multiply(cost.cost.prompt_token, event.properties['$ai_input_tokens'] || 0)
    )
    event.properties['$ai_output_cost_usd'] = parseFloat(
        bigDecimal.multiply(cost.cost.completion_token, event.properties['$ai_output_tokens'] || 0)
    )

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
    let cost = costs.find((cost) => cost.model.toLowerCase() === aiModel.toLowerCase())
    // Check if the model is a variant of a known model
    if (!cost) {
        cost = costs.find((cost) => aiModel.toLowerCase().includes(cost.model.toLowerCase()))
    }
    // Check if the model is a variant of a known model
    if (!cost) {
        cost = costs.find((cost) => cost.model.toLowerCase().includes(aiModel.toLowerCase()))
    }
    if (!cost) {
        console.warn(`No cost found for model: ${aiModel}`)
    }
    return cost
}
