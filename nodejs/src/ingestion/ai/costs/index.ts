import bigDecimal from 'js-big-decimal'

import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

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

const setCostsOnEvent = (event: EventWithProperties, cost: ResolvedModelCost): void => {
    const inputCost = calculateInputCost(event, cost)
    const outputCost = calculateOutputCost(event, cost)
    const requestCost = calculateRequestCost(event, cost)
    const webSearchCost = calculateWebSearchCost(event, cost)

    event.properties['$ai_input_cost_usd'] = parseFloat(inputCost)
    event.properties['$ai_output_cost_usd'] = parseFloat(outputCost)
    event.properties['$ai_request_cost_usd'] = parseFloat(requestCost)
    event.properties['$ai_web_search_cost_usd'] = parseFloat(webSearchCost)

    // Sum all cost components for total using strings (BigDecimal returns strings)
    let total = bigDecimal.add(inputCost, outputCost)
    total = bigDecimal.add(total, requestCost)
    total = bigDecimal.add(total, webSearchCost)

    event.properties['$ai_total_cost_usd'] = parseFloat(total)
}

const isString = (property: unknown): property is string => {
    return typeof property === 'string'
}

const isBigDecimalInput = (value: unknown): value is string | number => {
    return typeof value === 'string' || typeof value === 'number'
}

/**
 * Process cost calculation for AI generation/embedding events.
 * Calculates input, output, request, and web search costs based on model pricing.
 */
export const processCost = (event: EventWithProperties): EventWithProperties => {
    const inputCost = event.properties['$ai_input_cost_usd']
    const outputCost = event.properties['$ai_output_cost_usd']

    // If we already have valid input and output costs, we can skip the rest of the logic
    if (inputCost && outputCost && isBigDecimalInput(inputCost) && isBigDecimalInput(outputCost)) {
        if (!event.properties['$ai_total_cost_usd']) {
            let total = bigDecimal.add(inputCost, outputCost)

            // Add pre-calculated request cost if present
            const requestCost = event.properties['$ai_request_cost_usd']
            if (requestCost && isBigDecimalInput(requestCost)) {
                total = bigDecimal.add(total, requestCost)
            }

            // Add pre-calculated web search cost if present
            const webSearchCost = event.properties['$ai_web_search_cost_usd']
            if (webSearchCost && isBigDecimalInput(webSearchCost)) {
                total = bigDecimal.add(total, webSearchCost)
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

/**
 * Extract core model parameters from $ai_model_parameters to top-level properties.
 */
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
