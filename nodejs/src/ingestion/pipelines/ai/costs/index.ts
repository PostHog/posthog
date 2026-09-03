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

const COST_COMPONENT_PROPERTIES = [
    '$ai_input_cost_usd',
    '$ai_output_cost_usd',
    '$ai_request_cost_usd',
    '$ai_web_search_cost_usd',
] as const

const PRECALCULATED_COST_PROPERTIES = [...COST_COMPONENT_PROPERTIES, '$ai_total_cost_usd'] as const

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

// Every token count each cost calculator reads, split by the side it prices.
// Presence is what matters, not value: `0` is a usage report that says the
// model consumed nothing, while an absent property means the provider never
// reported usage at all. The sides gate independently, because an interrupted
// stream often reports one side only — Anthropic sends input tokens on
// message_start and the output count in the final delta.
//
// Hand-maintained, so a calculator that starts reading a new token property has
// to add it to its side's list too. Leave it out and an event carrying only
// that property prices as unknown. Properties that modality extraction writes
// but no calculator reads, such as `$ai_text_input_tokens`, do not belong here.
//
// The validation step (steps/validate-ai-event-tokens.ts) sanitizes only a
// core subset of these. That is safe: every calculator read goes through
// finiteNumberOrUndefined, which treats an unusable value as absent.
const INPUT_TOKEN_COUNT_PROPERTIES = [
    '$ai_input_tokens',
    '$ai_cache_read_input_tokens',
    '$ai_cache_creation_input_tokens',
    '$ai_cache_creation_5m_input_tokens',
    '$ai_cache_creation_1h_input_tokens',
    '$ai_audio_input_tokens',
    '$ai_image_input_tokens',
    '$ai_cache_read_audio_tokens',
] as const

const OUTPUT_TOKEN_COUNT_PROPERTIES = [
    '$ai_output_tokens',
    '$ai_text_output_tokens',
    '$ai_reasoning_tokens',
    '$ai_audio_output_tokens',
    '$ai_image_output_tokens',
] as const

const hasAnyTokenCount = (properties: Properties, keys: readonly string[]): boolean => {
    return keys.some((key) => finiteNumberOrUndefined(properties[key]) !== undefined)
}

const setCostsOnEvent = (event: EventWithProperties, cost: ResolvedModelCost): void => {
    // Neither of these reads a token count. A per-request charge bills for the
    // call itself, and a web search charge bills a count the provider reported,
    // so both stay known when the token counts are not.
    const requestCost = calculateRequestCost(event, cost)
    const webSearchCost = calculateWebSearchCost(event, cost)
    const hasNonTokenCost = parseFloat(requestCost) > 0 || parseFloat(webSearchCost) > 0

    // Costs the client computed themselves are costs we know. They survive
    // parsePrecalculatedCosts only as numbers, so presence is the test. One-sided
    // costs never reach the passthrough early return, which needs both input and
    // output, so they have to be caught here.
    const hasClientCost = PRECALCULATED_COST_PROPERTIES.some((key) => typeof event.properties[key] === 'number')

    const hasInputTokenCount = hasAnyTokenCount(event.properties, INPUT_TOKEN_COUNT_PROPERTIES)
    const hasOutputTokenCount = hasAnyTokenCount(event.properties, OUTPUT_TOKEN_COUNT_PROPERTIES)

    // A token rate multiplied by no usage is 0, which reads as "this call was
    // free" rather than "we never learned what this call used". The two are
    // different facts, and only one of them is true for an aborted stream: it is
    // billed for the tokens it consumed, we just never received the count. Leave
    // the costs unset so downstream can say it does not know — but only when
    // nothing at all priced this call.
    if (!hasInputTokenCount && !hasOutputTokenCount && !hasNonTokenCost && !hasClientCost) {
        aiCostTotalOutcomeCounter.labels({ outcome: 'unknown' }).inc()
        return
    }

    // Each side's cost is a token rate times that side's counts, so a side
    // without counts is unknown, not zero. One reported side must not fabricate
    // a $0 for the other. The other two components stay known either way.
    if (hasInputTokenCount) {
        const inputCost = calculateInputCost(event, cost)
        setPropertyIfValidOrMissing(event.properties, '$ai_input_cost_usd', parseFloat(inputCost))
    }
    if (hasOutputTokenCount) {
        const outputCost = calculateOutputCost(event, cost)
        setPropertyIfValidOrMissing(event.properties, '$ai_output_cost_usd', parseFloat(outputCost))
    }
    setPropertyIfValidOrMissing(event.properties, '$ai_request_cost_usd', parseFloat(requestCost))
    setPropertyIfValidOrMissing(event.properties, '$ai_web_search_cost_usd', parseFloat(webSearchCost))

    if (typeof event.properties['$ai_total_cost_usd'] === 'number') {
        return
    }

    // A sum over the known components is still a known total; the unset ones
    // stay unset rather than contributing a zero they never asserted.
    let total = '0'
    for (const key of COST_COMPONENT_PROPERTIES) {
        const value = event.properties[key]
        if (typeof value === 'number') {
            total = bigDecimal.add(total, String(value))
        }
    }
    const totalCost = parseFloat(total)
    event.properties['$ai_total_cost_usd'] = totalCost
    trackCostOutcome(totalCost)
}

const isString = (property: unknown): property is string => {
    return typeof property === 'string'
}

// Ingestion can deliver the flag JSON-serialized, so the string "true" also counts as set.
const isCostPassthrough = (value: unknown): boolean => value === true || value === 'true'

/**
 * Process cost calculation for AI generation/embedding events.
 * Calculates input, output, request, and web search costs based on model pricing.
 */
export const processCost = (event: EventWithProperties): EventWithProperties => {
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
    // Zero is a usable total here because a gateway that charges nothing, such as
    // under BYOK, reports zero. The branch above instead reads a zero input or
    // output cost as absent.
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

    // An explicit $ai_service_tier (gateway emitters) wins over the served tier the
    // @posthog/ai SDK records in the model parameters.
    if (params.service_tier !== undefined && event.properties.$ai_service_tier === undefined) {
        event.properties.$ai_service_tier = params.service_tier
    }

    return event
}
