import bigDecimal from 'js-big-decimal'

import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { aiCostLookupCounter } from '../metrics'
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

const setPropertyIfValidOrMissing = (properties: Properties, key: string, value: number): void => {
    const existingValue = properties[key]
    if (existingValue !== null && existingValue !== undefined && isBigDecimalInput(existingValue)) {
        return
    }
    if (!Number.isNaN(value)) {
        properties[key] = value
    }
}

const isBigDecimalInput = (value: unknown): value is string | number => {
    return typeof value === 'string' || typeof value === 'number'
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

    const existingTotal = event.properties['$ai_total_cost_usd']
    if (existingTotal !== null && existingTotal !== undefined && isBigDecimalInput(existingTotal)) {
        return
    }

    event.properties['$ai_total_cost_usd'] = parseFloat(
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
}

const isString = (property: unknown): property is string => {
    return typeof property === 'string'
}

/**
 * Extract modality-specific token counts from raw provider usage metadata.
 * Currently supports Gemini's candidatesTokensDetails for image token breakdown.
 * Removes $ai_usage from properties after extraction.
 */
export const extractModalityTokens = (event: EventWithProperties): EventWithProperties => {
    const usage = event.properties['$ai_usage']

    if (!usage || typeof usage !== 'object') {
        return event
    }

    // Helper function to extract tokens from either array or object format
    const extractTokensFromDetails = (tokenDetails: unknown): void => {
        if (!tokenDetails) {
            return
        }

        // Array format: [{ modality: "TEXT", tokenCount: 10 }, { modality: "IMAGE", tokenCount: 1290 }]
        // Gemini returns uppercase modality values (TEXT, IMAGE, AUDIO)
        if (Array.isArray(tokenDetails)) {
            for (const detail of tokenDetails) {
                if (detail && typeof detail === 'object') {
                    const modality = (detail as Record<string, unknown>)['modality']
                    const tokenCount = (detail as Record<string, unknown>)['tokenCount']

                    if (typeof modality === 'string' && typeof tokenCount === 'number') {
                        const modalityLower = modality.toLowerCase()

                        if (modalityLower === 'image' && tokenCount > 0) {
                            event.properties['$ai_image_output_tokens'] = tokenCount
                        }
                        if (modalityLower === 'text') {
                            event.properties['$ai_text_output_tokens'] = tokenCount
                        }
                    }
                }
            }
        }
        // Object format fallback: { textTokens: number, imageTokens: number }
        // Defensive handling in case format changes or for testing
        else if (typeof tokenDetails === 'object') {
            const details = tokenDetails as Record<string, unknown>

            if (typeof details['imageTokens'] === 'number' && details['imageTokens'] > 0) {
                event.properties['$ai_image_output_tokens'] = details['imageTokens']
            }

            if (typeof details['textTokens'] === 'number') {
                event.properties['$ai_text_output_tokens'] = details['textTokens']
            }
        }
    }

    // Handle Gemini's candidatesTokensDetails (or outputTokenDetails in some versions)
    // Gemini returns: [{ modality: "TEXT", tokenCount: 10 }, { modality: "IMAGE", tokenCount: 1290 }]
    // Also supports object format as defensive fallback: { textTokens: 10, imageTokens: 1290 }
    const tokenDetails =
        (usage as Record<string, unknown>)['candidatesTokensDetails'] ??
        (usage as Record<string, unknown>)['outputTokenDetails']

    extractTokensFromDetails(tokenDetails)

    // Check for Vercel AI SDK with rawResponse at top level: { rawResponse: { usageMetadata: {...} } }
    // This is the current path when using Vercel AI SDK with Google provider
    const topLevelRawResponse = (usage as Record<string, unknown>)['rawResponse']
    if (topLevelRawResponse && typeof topLevelRawResponse === 'object') {
        const topLevelUsageMetadata = (topLevelRawResponse as Record<string, unknown>)['usageMetadata']
        if (topLevelUsageMetadata && typeof topLevelUsageMetadata === 'object') {
            const topLevelTokenDetails =
                (topLevelUsageMetadata as Record<string, unknown>)['candidatesTokensDetails'] ??
                (topLevelUsageMetadata as Record<string, unknown>)['outputTokenDetails']

            extractTokensFromDetails(topLevelTokenDetails)
        }
    }

    // Check for Vercel AI SDK structure: { usage: {...}, providerMetadata: { google: {...} } }
    const providerMetadata = (usage as Record<string, unknown>)['providerMetadata']
    if (providerMetadata && typeof providerMetadata === 'object') {
        const googleMetadata = (providerMetadata as Record<string, unknown>)['google']
        if (googleMetadata && typeof googleMetadata === 'object') {
            const googleTokenDetails =
                (googleMetadata as Record<string, unknown>)['candidatesTokensDetails'] ??
                (googleMetadata as Record<string, unknown>)['outputTokenDetails']

            extractTokensFromDetails(googleTokenDetails)
        }
    }

    // Check for nested rawUsage structure: { rawUsage: { providerMetadata: { google: {...} } } }
    // This happens when the SDK wraps the raw provider response
    const rawUsage = (usage as Record<string, unknown>)['rawUsage']
    if (rawUsage && typeof rawUsage === 'object') {
        const rawProviderMetadata = (rawUsage as Record<string, unknown>)['providerMetadata']
        if (rawProviderMetadata && typeof rawProviderMetadata === 'object') {
            const rawGoogleMetadata = (rawProviderMetadata as Record<string, unknown>)['google']
            if (rawGoogleMetadata && typeof rawGoogleMetadata === 'object') {
                const rawGoogleTokenDetails =
                    (rawGoogleMetadata as Record<string, unknown>)['candidatesTokensDetails'] ??
                    (rawGoogleMetadata as Record<string, unknown>)['outputTokenDetails']

                extractTokensFromDetails(rawGoogleTokenDetails)
            }
        }

        // Check for Vercel AI SDK V3 structure: { rawUsage: { usage: { raw: {...} } } }
        // In Vercel AI SDK, Gemini's raw response is at usage.raw.candidatesTokensDetails
        const rawUsageUsage = (rawUsage as Record<string, unknown>)['usage']
        if (rawUsageUsage && typeof rawUsageUsage === 'object') {
            const rawUsageRaw = (rawUsageUsage as Record<string, unknown>)['raw']
            if (rawUsageRaw && typeof rawUsageRaw === 'object') {
                const vercelRawTokenDetails =
                    (rawUsageRaw as Record<string, unknown>)['candidatesTokensDetails'] ??
                    (rawUsageRaw as Record<string, unknown>)['outputTokenDetails']

                extractTokensFromDetails(vercelRawTokenDetails)
            }
        }

        // Check for Vercel AI SDK with rawResponse: { rawUsage: { rawResponse: { usageMetadata: {...} } } }
        // This is the path when using Vercel AI SDK with Google provider
        const rawResponse = (rawUsage as Record<string, unknown>)['rawResponse']
        if (rawResponse && typeof rawResponse === 'object') {
            const usageMetadata = (rawResponse as Record<string, unknown>)['usageMetadata']
            if (usageMetadata && typeof usageMetadata === 'object') {
                const rawResponseTokenDetails =
                    (usageMetadata as Record<string, unknown>)['candidatesTokensDetails'] ??
                    (usageMetadata as Record<string, unknown>)['outputTokenDetails']

                extractTokensFromDetails(rawResponseTokenDetails)
            }
        }
    }

    // Remove raw usage from properties after extraction
    delete event.properties['$ai_usage']

    return event
}

/**
 * Process cost calculation for AI generation/embedding events.
 * Calculates input, output, request, and web search costs based on model pricing.
 */
export const processCost = (event: EventWithProperties): EventWithProperties => {
    // First, extract modality tokens from raw usage if present
    extractModalityTokens(event)

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
