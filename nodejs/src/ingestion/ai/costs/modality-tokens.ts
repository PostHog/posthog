import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { aiCostModalityExtractionCounter } from '../metrics'

export interface EventWithProperties extends PluginEvent {
    properties: Properties
}

/**
 * Extract modality-specific token counts from raw provider usage metadata.
 * Currently supports Gemini's candidatesTokensDetails for image token breakdown.
 * Removes $ai_usage from properties after extraction.
 */
export const extractModalityTokens = (event: EventWithProperties): EventWithProperties => {
    const usage = event.properties['$ai_usage']

    if (!usage || typeof usage !== 'object') {
        delete event.properties['$ai_usage']
        return event
    }

    try {
        let extractedTokens = false

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
                                extractedTokens = true
                            }
                            if (modalityLower === 'text') {
                                event.properties['$ai_text_output_tokens'] = tokenCount
                                extractedTokens = true
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
                    extractedTokens = true
                }

                if (typeof details['textTokens'] === 'number') {
                    event.properties['$ai_text_output_tokens'] = details['textTokens']
                    extractedTokens = true
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

        // Track extraction outcomes for monitoring
        if (extractedTokens) {
            aiCostModalityExtractionCounter.labels({ status: 'extracted' }).inc()
        } else {
            aiCostModalityExtractionCounter.labels({ status: 'no_details' }).inc()
        }
    } finally {
        // CRITICAL: Always delete $ai_usage to prevent it from being stored in ClickHouse
        // This must happen regardless of whether extraction succeeds or fails
        delete event.properties['$ai_usage']
    }

    return event
}
