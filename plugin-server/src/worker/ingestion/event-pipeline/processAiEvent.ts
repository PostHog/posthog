import { PluginEvent } from '@posthog/plugin-scaffold'
import bigDecimal from 'js-big-decimal'

import { ModelRow } from '../../../types'
import { providers } from '../../../utils/ai-cost-data/mappings'

export const processAiEvent = (event: PluginEvent): PluginEvent => {
    if ((event.event !== '$ai_generation' && event.event !== '$ai_embedding') || !event.properties) {
        return event
    }

    if (!event.properties['$ai_provider'] || !event.properties['$ai_model']) {
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
