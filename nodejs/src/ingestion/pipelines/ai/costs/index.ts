import bigDecimal from 'js-big-decimal'

import { aiCostLookupCounter, aiCostTotalOutcomeCounter } from '~/ingestion/pipelines/ai/metrics'
import { PluginEvent, Properties } from '~/plugin-scaffold'

import {
    CostModelResult,
    CostModelSource,
    findCostFromModel,
    getNewModelName,
    requireSpecialCost,
} from './cost-model-matching'
import { finiteNumberOrUndefined } from './cost-utils'
import { calculateInputCost } from './input-costs'
import { extractModalityTokens } from './modality-tokens'
import { calculateOutputCost } from './output-costs'
import { ResolvedModelCost } from './providers/types'
import { calculateRequestCost } from './request-costs'
import { calculateWebSearchCost } from './web-search-costs'

export interface EventWithProperties extends PluginEvent {
    properties: Properties
}

const PRECALCULATED_COST_PROPERTIES = [
    '$ai_input_cost_usd',
    '$ai_output_cost_usd',
    '$ai_request_cost_usd',
    '$ai_web_search_cost_usd',
    '$ai_total_cost_usd',
] as const

/**
 * Replace each cost the client sent with its parsed number, dropping the ones
 * `bigDecimal` can't use so they get recalculated instead of trusted. Checking a
 * value in place isn't enough — the check and the arithmetic have to agree on the
 * same value, or a string like `"0x10"` passes the check and still reaches
 * `bigDecimal`.
 */
const parsePrecalculatedCosts = (properties: Properties): void => {
    for (const key of PRECALCULATED_COST_PROPERTIES) {
        if (properties[key] === undefined) {
            continue
        }
        const parsed = finiteNumberOrUndefined(properties[key])
        if (parsed === undefined) {
            delete properties[key]
        } else {
            properties[key] = parsed
        }
    }
}

const setPropertyIfValidOrMissing = (properties: Properties, key: string, value: number): void => {
    if (typeof properties[key] === 'number') {
        return
    }
    if (!Number.isNaN(value)) {
        properties[key] = value
    }
}

const trackCostOutcome = (totalCost: number): void => {
    if (Number.isNaN(totalCost)) {
        aiCostTotalOutcomeCounter.labels({ outcome: 'error' }).inc()
    } else if (totalCost < 0) {
        aiCostTotalOutcomeCounter.labels({ outcome: 'negative' }).inc()
    } else if (totalCost === 0) {
        aiCostTotalOutcomeCounter.labels({ outcome: 'zero' }).inc()
    } else {
        aiCostTotalOutcomeCounter.labels({ outcome: 'positive' }).inc()
    }
}

const setCostsOnEvent = (event: EventWithProperties, cost: ResolvedModelCost): void => {
    const inputCost = calculateInputCost(event, cost)
    const outputCost = calculateOutputCost(event, cost)
    const requestCost = calculateRequestCost(event, cost)
    const webSearchCost = calculateWebSearchCost(event, cost)

    setPropertyIfValidOrMissing(event.properties, '$ai_input_cost_usd', parseFloat(inputCost))
    setPropertyIfValidOrMissing(event.properties, '$ai_output_cost_usd', parseFloat(outputCost))
    setPropertyIfValidOrMissing(event.properties, '$ai_request_cost_usd', parseFloat(requestCost))
    setPropertyIfValidOrMissing(event.properties, '$ai_web_search_cost_usd', parseFloat(webSearchCost))

    if (typeof event.properties['$ai_total_cost_usd'] === 'number') {
        return
    }

    const totalCost = parseFloat(
        bigDecimal.add(
            bigDecimal.add(
                String(event.properties['$ai_input_cost_usd']),
                String(event.properties['$ai_output_cost_usd'])
            ),
            bigDecimal.add(
                String(event.properties['$ai_request_cost_usd']),
                String(event.properties['$ai_web_search_cost_usd'])
            )
        )
    )
    event.properties['$ai_total_cost_usd'] = totalCost
    trackCostOutcome(totalCost)
}

const isString = (property: unknown): property is string => {
    return typeof property === 'string'
}

// Accept a boolean or its serialized string form.
const isCostPassthrough = (value: unknown): boolean => value === true || value === 'true'

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null

// An LLM gateway (Vercel AI Gateway, OpenRouter) augments the response usage
// object with the real charged cost as a `cost` field. SDK wrappers forward that
// raw usage under $ai_usage, the same blob modality extraction reads, so a
// base-url-proxied OpenAI/Anthropic/Responses call carries the gateway bill here.
// A standard provider usage object has no `cost` field, so its presence marks a
// gateway response. Check the documented forward locations: posthog-python sends
// the usage object at the top level; @posthog/ai nests it under usage.raw.
const extractGatewayReportedCost = (usage: unknown): number | undefined => {
    if (!isRecord(usage)) {
        return undefined
    }

    const candidates: unknown[] = [usage]

    const usageDetails = usage['usage']
    if (isRecord(usageDetails)) {
        candidates.push(usageDetails['raw'])
    }

    const rawUsage = usage['rawUsage']
    if (isRecord(rawUsage) && isRecord(rawUsage['usage'])) {
        candidates.push((rawUsage['usage'] as Record<string, unknown>)['raw'])
    }

    const providerMetadata = usage['providerMetadata']
    if (isRecord(providerMetadata)) {
        candidates.push(providerMetadata['gateway'])
    }

    for (const candidate of candidates) {
        if (isRecord(candidate)) {
            const cost = finiteNumberOrUndefined(candidate['cost'])
            if (cost !== undefined) {
                return cost
            }
        }
    }

    return undefined
}

/**
 * Process cost calculation for AI generation/embedding events.
 * Calculates input, output, request, and web search costs based on model pricing.
 */
export const processCost = (event: EventWithProperties): EventWithProperties => {
    // Adopt a gateway-reported cost as a passthrough total before modality
    // extraction deletes $ai_usage. Only when the caller set no usable total.
    if (finiteNumberOrUndefined(event.properties['$ai_total_cost_usd']) === undefined) {
        const gatewayCost = extractGatewayReportedCost(event.properties['$ai_usage'])
        if (gatewayCost !== undefined) {
            event.properties['$ai_total_cost_usd'] = gatewayCost
            event.properties['$ai_cost_passthrough'] = true
        }
    }

    // First, extract modality tokens from raw usage if present
    extractModalityTokens(event)

    parsePrecalculatedCosts(event.properties)

    const inputCost = event.properties['$ai_input_cost_usd']
    const outputCost = event.properties['$ai_output_cost_usd']

    // If we already have valid input and output costs, we can skip the rest of the logic
    if (inputCost && outputCost) {
        if (!event.properties['$ai_total_cost_usd']) {
            let total = bigDecimal.add(inputCost, outputCost)

            // Add pre-calculated request cost if present
            const requestCost = event.properties['$ai_request_cost_usd']
            if (requestCost) {
                total = bigDecimal.add(total, requestCost)
            }

            // Add pre-calculated web search cost if present
            const webSearchCost = event.properties['$ai_web_search_cost_usd']
            if (webSearchCost) {
                total = bigDecimal.add(total, webSearchCost)
            }

            const totalCost = parseFloat(total)
            event.properties['$ai_total_cost_usd'] = totalCost
            trackCostOutcome(totalCost)
        }

        event.properties['$ai_cost_model_source'] = CostModelSource.Passthrough
        return event
    }

    // $ai_cost_passthrough keeps a caller-reported total and skips estimation.
    // Require a usable total, so an empty cost is never labeled passthrough.
    if (isCostPassthrough(event.properties['$ai_cost_passthrough'])) {
        const total = event.properties['$ai_total_cost_usd']
        if (typeof total === 'number') {
            event.properties['$ai_cost_model_source'] = CostModelSource.Passthrough
            trackCostOutcome(total)
            return event
        }
    }

    // A non-numeric price throws inside js-big-decimal, so treat one as absent and
    // fall back to model pricing rather than billing at a rate of zero.
    const inputTokenPrice = finiteNumberOrUndefined(event.properties['$ai_input_token_price'])
    const outputTokenPrice = finiteNumberOrUndefined(event.properties['$ai_output_token_price'])

    if (inputTokenPrice !== undefined && outputTokenPrice !== undefined) {
        const customCost: ResolvedModelCost = {
            model: 'custom',
            provider: 'custom',
            cost: {
                prompt_token: inputTokenPrice,
                completion_token: outputTokenPrice,
                cache_read_token: finiteNumberOrUndefined(event.properties['$ai_cache_read_token_price']),
                cache_write_token: finiteNumberOrUndefined(event.properties['$ai_cache_write_token_price']),
                cache_write_1h_token: finiteNumberOrUndefined(event.properties['$ai_cache_write_1h_token_price']),
                request: finiteNumberOrUndefined(event.properties['$ai_request_price']),
                web_search: finiteNumberOrUndefined(event.properties['$ai_web_search_price']),
            },
        }

        setCostsOnEvent(event, customCost)

        event.properties['$ai_model_cost_used'] = 'custom'
        event.properties['$ai_cost_model_source'] = CostModelSource.Custom
        event.properties['$ai_cost_model_provider'] = 'custom'

        aiCostLookupCounter.labels({ status: 'custom' }).inc()
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
        aiCostLookupCounter.labels({ status: 'not_found' }).inc()
        return event
    }

    const { cost, source } = costResult

    setCostsOnEvent(event, cost)

    event.properties['$ai_model_cost_used'] = cost.model
    event.properties['$ai_cost_model_source'] = source
    event.properties['$ai_cost_model_provider'] = cost.provider

    aiCostLookupCounter.labels({ status: 'found' }).inc()
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
