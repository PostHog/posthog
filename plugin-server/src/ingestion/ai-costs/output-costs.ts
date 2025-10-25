import bigDecimal from 'js-big-decimal'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { ResolvedModelCost } from './providers/types'

const REASONING_COST_MODELS = [/^gemini-2.5-/]

const mustAddReasoningCost = (model: string): boolean => {
    return REASONING_COST_MODELS.some((candidate) => candidate.test(model.toLowerCase()))
}

export const calculateOutputCost = (event: PluginEvent, cost: ResolvedModelCost): string => {
    if (!event.properties) {
        return '0'
    }

    let outputTokens = event.properties['$ai_output_tokens'] || 0

    if (
        event.properties['$ai_reasoning_tokens'] &&
        event.properties['$ai_model'] &&
        mustAddReasoningCost(event.properties['$ai_model'])
    ) {
        outputTokens = bigDecimal.add(outputTokens, event.properties['$ai_reasoning_tokens'])
    }

    return bigDecimal.multiply(cost.cost.completion_token, outputTokens)
}
