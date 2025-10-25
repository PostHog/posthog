import bigDecimal from 'js-big-decimal'

import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { logger } from '../../utils/logger'
import {
    CostModelResult,
    CostModelSource,
    findCostFromModel,
    getNewModelName,
    requireSpecialCost,
} from './cost-model-matching'
import { calculateInputCost } from './input-costs'
import { calculateOutputCost } from './output-costs'
import { ResolvedModelCost } from './providers/types'
import { calculateRequestCost } from './request-costs'
import { calculateWebSearchCost } from './web-search-costs'

export interface EventWithProperties extends PluginEvent {
    properties: Properties
}

const isEventWithProperties = (event: PluginEvent): event is EventWithProperties => {
    return event.properties !== undefined && event.properties !== null
}

export const AI_EVENT_TYPES = new Set([
    '$ai_generation',
    '$ai_embedding',
    '$ai_span',
    '$ai_trace',
    '$ai_metric',
    '$ai_feedback',
])

export const processAiEvent = (event: PluginEvent): PluginEvent | EventWithProperties => {
    // If the event doesn't carry properties, there's nothing to do.
    if (!isEventWithProperties(event)) {
        return event
    }

    // Normalize trace properties for all AI events.
    const normalized: EventWithProperties = AI_EVENT_TYPES.has(event.event) ? normalizeTraceProperties(event) : event

    // Only generation/embedding events get cost processing and model param extraction.
    const isCosted = normalized.event === '$ai_generation' || normalized.event === '$ai_embedding'

    if (!isCosted) {
        return normalized
    }

    const eventWithCosts = processCost(normalized)

    return extractCoreModelParams(eventWithCosts)
}

export const normalizeTraceProperties = (event: EventWithProperties): EventWithProperties => {
    // List of properties that should always be strings
    const keys = ['$ai_trace_id', '$ai_parent_id', '$ai_span_id', '$ai_generation_id', '$ai_session_id']

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

const setCostsOnEvent = (event: EventWithProperties, cost: ResolvedModelCost): void => {
    event.properties['$ai_input_cost_usd'] = parseFloat(calculateInputCost(event, cost))
    event.properties['$ai_output_cost_usd'] = parseFloat(calculateOutputCost(event, cost))
    event.properties['$ai_request_cost_usd'] = parseFloat(calculateRequestCost(event, cost))
    event.properties['$ai_web_search_cost_usd'] = parseFloat(calculateWebSearchCost(event, cost))

    // Sum all cost components for total
    let total = bigDecimal.add(event.properties['$ai_input_cost_usd'], event.properties['$ai_output_cost_usd'])
    total = bigDecimal.add(total, event.properties['$ai_request_cost_usd'])
    total = bigDecimal.add(total, event.properties['$ai_web_search_cost_usd'])

    event.properties['$ai_total_cost_usd'] = parseFloat(total)
}

const processCost = (event: EventWithProperties): EventWithProperties => {
    // If we already have input and output costs, we can skip the rest of the logic
    if (event.properties['$ai_input_cost_usd'] && event.properties['$ai_output_cost_usd']) {
        if (!event.properties['$ai_total_cost_usd']) {
            let total = bigDecimal.add(event.properties['$ai_input_cost_usd'], event.properties['$ai_output_cost_usd'])

            // Add pre-calculated request cost if present
            if (event.properties['$ai_request_cost_usd']) {
                total = bigDecimal.add(total, event.properties['$ai_request_cost_usd'])
            }

            // Add pre-calculated web search cost if present
            if (event.properties['$ai_web_search_cost_usd']) {
                total = bigDecimal.add(total, event.properties['$ai_web_search_cost_usd'])
            }

            event.properties['$ai_total_cost_usd'] = parseFloat(total)
        }

        return event
    }

    // If custom token pricing is provided, use it to calculate costs
    const hasCustomPricing =
        event.properties['$ai_input_token_price'] !== undefined &&
        event.properties['$ai_output_token_price'] !== undefined

    if (hasCustomPricing) {
        const customCost: ResolvedModelCost = {
            model: 'custom',
            provider: 'custom',
            cost: {
                prompt_token: event.properties['$ai_input_token_price'],
                completion_token: event.properties['$ai_output_token_price'],
                cache_read_token: event.properties['$ai_cache_read_token_price'],
                cache_write_token: event.properties['$ai_cache_write_token_price'],
                request: event.properties['$ai_request_price'],
                web_search: event.properties['$ai_web_search_price'],
            },
        }

        setCostsOnEvent(event, customCost)

        event.properties['$ai_model_cost_used'] = 'custom'
        event.properties['$ai_cost_model_source'] = CostModelSource.Custom
        event.properties['$ai_cost_model_provider'] = 'custom'

        return event
    }

    if (!event.properties['$ai_model']) {
        return event
    }

    const model: unknown = event.properties['$ai_model']

    let parsedModel: string

    if (!isString(model)) {
        return event
    }

    parsedModel = model

    if (requireSpecialCost(parsedModel)) {
        parsedModel = getNewModelName(parsedModel, event.properties['$ai_input_tokens'])
    }

    const costResult: CostModelResult | undefined = findCostFromModel(parsedModel, event.properties)

    if (!costResult) {
        return event
    }

    const { cost, source } = costResult

    setCostsOnEvent(event, cost)

    event.properties['$ai_model_cost_used'] = cost.model
    event.properties['$ai_cost_model_source'] = source
    event.properties['$ai_cost_model_provider'] = cost.provider

    return event
}

export const extractCoreModelParams = (event: EventWithProperties): EventWithProperties => {
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

const isString = (property: unknown): property is string => {
    return typeof property === 'string'
}
