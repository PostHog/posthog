import { PluginEvent, Properties } from '~/plugin-scaffold'

import { aiCostModalityExtractionCounter } from '../metrics'

export interface EventWithProperties extends PluginEvent {
    properties: Properties
}

const isObject = (value: unknown): value is Record<string, unknown> => {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

type ExtractionSource = 'gemini_input' | 'gemini_output' | 'gemini_cache' | 'openai_input' | 'openai_cache'

/**
 * Extract modality-specific token counts from raw provider usage metadata.
 * Supports Gemini's promptTokensDetails (input modality), candidatesTokensDetails
 * (output modality), and cacheTokensDetails (cache modality), plus the OpenAI
 * equivalents under prompt_tokens_details. Removes $ai_usage from properties
 * after extraction so it does not get persisted to ClickHouse.
 */
export const extractModalityTokens = (event: EventWithProperties): EventWithProperties => {
    const usage = event.properties['$ai_usage']

    if (!usage || typeof usage !== 'object') {
        delete event.properties['$ai_usage']
        return event
    }

    try {
        const extractedSources = new Set<ExtractionSource>()

        // Gemini's promptTokensDetails shape (input modality).
        // Array form: [{ modality: "AUDIO", tokenCount: 750 }, { modality: "TEXT", tokenCount: 598 }]
        // Object form: { audioTokens: 750, textTokens: 598 } (defensive fallback)
        const extractInputModality = (tokenDetails: unknown): void => {
            if (!tokenDetails) {
                return
            }

            if (Array.isArray(tokenDetails)) {
                for (const detail of tokenDetails) {
                    if (!isObject(detail)) {
                        continue
                    }
                    const modality = detail['modality']
                    const tokenCount = detail['tokenCount']
                    if (typeof modality !== 'string' || typeof tokenCount !== 'number') {
                        continue
                    }
                    const modalityLower = modality.toLowerCase()
                    if (modalityLower === 'audio' && tokenCount > 0) {
                        event.properties['$ai_audio_input_tokens'] = tokenCount
                        extractedSources.add('gemini_input')
                    }
                    if (modalityLower === 'image' && tokenCount > 0) {
                        event.properties['$ai_image_input_tokens'] = tokenCount
                        extractedSources.add('gemini_input')
                    }
                    if (modalityLower === 'text') {
                        event.properties['$ai_text_input_tokens'] = tokenCount
                        extractedSources.add('gemini_input')
                    }
                }
            } else if (isObject(tokenDetails)) {
                if (typeof tokenDetails['audioTokens'] === 'number' && tokenDetails['audioTokens'] > 0) {
                    event.properties['$ai_audio_input_tokens'] = tokenDetails['audioTokens']
                    extractedSources.add('gemini_input')
                }
                if (typeof tokenDetails['imageTokens'] === 'number' && tokenDetails['imageTokens'] > 0) {
                    event.properties['$ai_image_input_tokens'] = tokenDetails['imageTokens']
                    extractedSources.add('gemini_input')
                }
                if (typeof tokenDetails['textTokens'] === 'number') {
                    event.properties['$ai_text_input_tokens'] = tokenDetails['textTokens']
                    extractedSources.add('gemini_input')
                }
            }
        }

        // Gemini's candidatesTokensDetails shape (output modality).
        // Array form: [{ modality: "TEXT", tokenCount: 10 }, { modality: "IMAGE", tokenCount: 1290 }]
        // Object form: { textTokens: 10, imageTokens: 1290 } (defensive fallback)
        const extractOutputModality = (tokenDetails: unknown): void => {
            if (!tokenDetails) {
                return
            }

            if (Array.isArray(tokenDetails)) {
                for (const detail of tokenDetails) {
                    if (!isObject(detail)) {
                        continue
                    }
                    const modality = detail['modality']
                    const tokenCount = detail['tokenCount']
                    if (typeof modality !== 'string' || typeof tokenCount !== 'number') {
                        continue
                    }
                    const modalityLower = modality.toLowerCase()
                    if (modalityLower === 'image' && tokenCount > 0) {
                        event.properties['$ai_image_output_tokens'] = tokenCount
                        extractedSources.add('gemini_output')
                    }
                    if (modalityLower === 'text') {
                        event.properties['$ai_text_output_tokens'] = tokenCount
                        extractedSources.add('gemini_output')
                    }
                }
            } else if (isObject(tokenDetails)) {
                if (typeof tokenDetails['imageTokens'] === 'number' && tokenDetails['imageTokens'] > 0) {
                    event.properties['$ai_image_output_tokens'] = tokenDetails['imageTokens']
                    extractedSources.add('gemini_output')
                }
                if (typeof tokenDetails['textTokens'] === 'number') {
                    event.properties['$ai_text_output_tokens'] = tokenDetails['textTokens']
                    extractedSources.add('gemini_output')
                }
            }
        }

        // Gemini's cacheTokensDetails shape (cache modality).
        // Array form: [{ modality: "AUDIO", tokenCount: 50 }, { modality: "TEXT", tokenCount: 250 }]
        // Object form: { audioTokens: 50 } (defensive fallback)
        const extractCacheModality = (tokenDetails: unknown): void => {
            if (!tokenDetails) {
                return
            }

            if (Array.isArray(tokenDetails)) {
                for (const detail of tokenDetails) {
                    if (!isObject(detail)) {
                        continue
                    }
                    const modality = detail['modality']
                    const tokenCount = detail['tokenCount']
                    if (typeof modality !== 'string' || typeof tokenCount !== 'number') {
                        continue
                    }
                    if (modality.toLowerCase() === 'audio' && tokenCount > 0) {
                        event.properties['$ai_cache_read_audio_tokens'] = tokenCount
                        extractedSources.add('gemini_cache')
                    }
                }
            } else if (
                isObject(tokenDetails) &&
                typeof tokenDetails['audioTokens'] === 'number' &&
                tokenDetails['audioTokens'] > 0
            ) {
                event.properties['$ai_cache_read_audio_tokens'] = tokenDetails['audioTokens']
                extractedSources.add('gemini_cache')
            }
        }

        // OpenAI shape: { prompt_tokens_details: { audio_tokens: 200, cached_tokens_details: { audio_tokens: 50 } } }
        // gpt-audio / gpt-realtime expose total prompt audio at audio_tokens, and
        // cached audio inside cached_tokens_details.audio_tokens.
        const extractOpenAIInputModality = (metadata: Record<string, unknown>): void => {
            const promptDetails = metadata['prompt_tokens_details']
            if (!isObject(promptDetails)) {
                return
            }
            const audioTokens = promptDetails['audio_tokens']
            if (typeof audioTokens === 'number' && audioTokens > 0) {
                event.properties['$ai_audio_input_tokens'] = audioTokens
                extractedSources.add('openai_input')
            }
        }

        const extractOpenAICacheModality = (metadata: Record<string, unknown>): void => {
            const promptDetails = metadata['prompt_tokens_details']
            if (!isObject(promptDetails)) {
                return
            }
            const cachedDetails = promptDetails['cached_tokens_details']
            if (!isObject(cachedDetails)) {
                return
            }
            const audioTokens = cachedDetails['audio_tokens']
            if (typeof audioTokens === 'number' && audioTokens > 0) {
                event.properties['$ai_cache_read_audio_tokens'] = audioTokens
                extractedSources.add('openai_cache')
            }
        }

        // Walk each `usage`-shaped metadata object encountered across the SDK
        // wrapper variants and pull every modality breakdown it exposes.
        const extractFromMetadata = (metadata: unknown): void => {
            if (!isObject(metadata)) {
                return
            }
            extractInputModality(metadata['promptTokensDetails'])
            extractOutputModality(metadata['candidatesTokensDetails'] ?? metadata['outputTokenDetails'])
            extractCacheModality(metadata['cacheTokensDetails'])
            extractOpenAIInputModality(metadata)
            extractOpenAICacheModality(metadata)
        }

        extractFromMetadata(usage)

        // Vercel AI SDK with rawResponse at top level: { rawResponse: { usageMetadata: {...} } }
        const topLevelRawResponse = (usage as Record<string, unknown>)['rawResponse']
        if (isObject(topLevelRawResponse)) {
            extractFromMetadata(topLevelRawResponse['usageMetadata'])
        }

        // Vercel AI SDK V2 structure: { providerMetadata: { google: {...} } }
        const providerMetadata = (usage as Record<string, unknown>)['providerMetadata']
        if (isObject(providerMetadata)) {
            extractFromMetadata(providerMetadata['google'])
        }

        // Vercel AI SDK V3 / nested rawUsage variants:
        //   { rawUsage: { providerMetadata: { google: {...} } } }
        //   { rawUsage: { usage: { raw: {...} } } }
        //   { rawUsage: { rawResponse: { usageMetadata: {...} } } }
        const rawUsage = (usage as Record<string, unknown>)['rawUsage']
        if (isObject(rawUsage)) {
            const rawProviderMetadata = rawUsage['providerMetadata']
            if (isObject(rawProviderMetadata)) {
                extractFromMetadata(rawProviderMetadata['google'])
            }

            const rawUsageUsage = rawUsage['usage']
            if (isObject(rawUsageUsage)) {
                extractFromMetadata(rawUsageUsage['raw'])
            }

            const rawResponse = rawUsage['rawResponse']
            if (isObject(rawResponse)) {
                extractFromMetadata(rawResponse['usageMetadata'])
            }
        }

        // Emit one counter increment per source that found something. An event
        // with both Gemini output and Gemini cache extraction increments twice
        // (once with source=gemini_output, once with source=gemini_cache). Sort
        // for deterministic ordering across runs — useful for tests and for
        // anyone reasoning about the metric stream.
        if (extractedSources.size === 0) {
            aiCostModalityExtractionCounter.labels({ status: 'no_details', source: 'none' }).inc()
        } else {
            for (const source of [...extractedSources].sort()) {
                aiCostModalityExtractionCounter.labels({ status: 'extracted', source }).inc()
            }
        }
    } finally {
        // CRITICAL: Always delete $ai_usage to prevent it from being stored in ClickHouse
        // This must happen regardless of whether extraction succeeds or fails
        delete event.properties['$ai_usage']
    }

    return event
}
