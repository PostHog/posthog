import bigDecimal from 'js-big-decimal'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { logger } from '../../utils/logger'
import { CostModelSource, findCostFromModel, getNewModelName, requireSpecialCost } from './cost-model-matching'
import { calculateInputCost } from './input-costs'
import { calculateOutputCost } from './output-costs'
import { ModelRow } from './providers/types'

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

const setCostsOnEvent = (event: PluginEvent, cost: ModelRow): void => {
    if (!event.properties) {
        return
    }

    event.properties['$ai_input_cost_usd'] = parseFloat(calculateInputCost(event, cost))
    event.properties['$ai_output_cost_usd'] = parseFloat(calculateOutputCost(event, cost))

    event.properties['$ai_total_cost_usd'] = parseFloat(
        bigDecimal.add(event.properties['$ai_input_cost_usd'], event.properties['$ai_output_cost_usd'])
    )
}

const processCost = (event: PluginEvent) => {
    if (!event.properties) {
        return event
    }

    // If we already have input and output costs, we can skip the rest of the logic
    if (event.properties['$ai_input_cost_usd'] && event.properties['$ai_output_cost_usd']) {
        if (!event.properties['$ai_total_cost_usd']) {
            event.properties['$ai_total_cost_usd'] = parseFloat(
                bigDecimal.add(event.properties['$ai_input_cost_usd'], event.properties['$ai_output_cost_usd'])
            )
        }

        return event
    }

    // If custom token pricing is provided, use it to calculate costs
    const hasCustomPricing =
        event.properties['$ai_input_token_price'] !== undefined &&
        event.properties['$ai_output_token_price'] !== undefined

    if (hasCustomPricing) {
        const customCost: ModelRow = {
            model: 'custom',
            cost: {
                prompt_token: event.properties['$ai_input_token_price'],
                completion_token: event.properties['$ai_output_token_price'],
                cache_read_token: event.properties['$ai_cache_read_token_price'],
                cache_write_token: event.properties['$ai_cache_write_token_price'],
            },
        }

        setCostsOnEvent(event, customCost)

        event.properties['$ai_model_cost_used'] = 'custom'
        event.properties['$ai_cost_model_source'] = CostModelSource.Custom

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

    setCostsOnEvent(event, cost)

    event.properties['$ai_model_cost_used'] = cost.model
    event.properties['$ai_cost_model_source'] = source

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
