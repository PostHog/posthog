import { PluginEvent } from '@posthog/plugin-scaffold'
import bigDecimal from 'js-big-decimal'

import { ModelRow } from '../../../types'
import { providers } from '../../../utils/ai-cost-data/mappings'

export const processAiEvent = (event: PluginEvent): PluginEvent => {
    if ((event.event !== '$ai_generation' && event.event !== '$ai_embedding') || !event.properties) {
        return event
    }
    event = processCost(event)
    event = extractCoreModelParams(event)
    return event
}

const processCost = (event: PluginEvent) => {
    if (!event.properties || !event.properties['$ai_provider'] || !event.properties['$ai_model']) {
        return event
    }

    const provider = providers.find((provider) => event?.properties?.$ai_provider === provider.provider.toLowerCase())
    if (!provider || !provider.costs) {
        return event
    }

    const cost = findCostFromModel(provider.costs, event.properties['$ai_model'])
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

const findCostFromModel = (costs: ModelRow[], aiModel: string): ModelRow | undefined => {
    return costs.find((cost) => {
        const valueLower = cost.model.value.toLowerCase()
        if (cost.model.operator === 'startsWith') {
            return aiModel.startsWith(valueLower)
        } else if (cost.model.operator === 'includes') {
            return aiModel.includes(valueLower)
        }
        return valueLower === aiModel
    })
}
