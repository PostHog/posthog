import bigDecimal from 'js-big-decimal'

import { PluginEvent } from '~/plugin-scaffold'

import { logger } from '../../../utils/logger'
import { numericProperty } from './cost-utils'
import { ResolvedModelCost } from './providers/types'

const matchProvider = (event: PluginEvent, provider: string): boolean => {
    if (!event.properties) {
        return false
    }

    const { $ai_provider: eventProvider, $ai_model: eventModel } = event.properties
    const normalizedProvider = provider.toLowerCase()
    const normalizedModel = eventModel?.toLowerCase()

    if (eventProvider?.toLowerCase() === normalizedProvider || normalizedModel?.includes(normalizedProvider)) {
        return true
    }

    // Claude models use Anthropic-style token counting regardless of provider (e.g., via Vertex)
    if (normalizedProvider === 'anthropic' && normalizedModel?.startsWith('claude')) {
        return true
    }

    return false
}

const usesInclusiveAnthropicInputTokens = (event: PluginEvent): boolean => {
    if (!event.properties) {
        return false
    }

    const provider = event.properties['$ai_provider']?.toLowerCase()
    const framework = event.properties['$ai_framework']?.toLowerCase()

    // Vercel AI Gateway reports input tokens inclusive of cache read/write tokens.
    return provider === 'gateway' && framework === 'vercel'
}

export const resolveCacheReportingExclusive = (event: PluginEvent): boolean => {
    if (!event.properties) {
        return false
    }

    const explicit = event.properties['$ai_cache_reporting_exclusive']
    if (typeof explicit === 'boolean') {
        return explicit
    }

    if (!matchProvider(event, 'anthropic')) {
        return false
    }

    if (!usesInclusiveAnthropicInputTokens(event)) {
        return true
    }

    const inputTokens = Number(event.properties['$ai_input_tokens'] || 0)
    const cacheReadTokens = Number(event.properties['$ai_cache_read_input_tokens'] || 0)
    const cacheWriteTokens = Number(event.properties['$ai_cache_creation_input_tokens'] || 0)
    return inputTokens < cacheReadTokens + cacheWriteTokens
}

/**
 * Clamp the residual text-token pool to zero when modality tokens are present
 * and the subtraction would push it negative. This guards against modality
 * counts that overlap with cache tokens or exceed the reported input total —
 * either case would otherwise produce a negative text contribution that
 * silently offsets the modality bill.
 */
const clampTextTokens = (value: string | number, hasModalityTokens: boolean): string | number => {
    if (!hasModalityTokens) {
        return value
    }
    const num = Number(value)
    return Number.isFinite(num) && num < 0 ? 0 : value
}

const warnMissingModalityRate = (event: PluginEvent, cost: ResolvedModelCost, modality: 'audio' | 'image'): void => {
    logger.warn('Missing modality rate; falling back to prompt rate', {
        modality,
        model: cost.model,
        provider: event.properties?.['$ai_provider'] || 'unknown',
    })
}

const computeAudioInputCost = (event: PluginEvent, cost: ResolvedModelCost, audioInputTokens: number): string => {
    if (audioInputTokens <= 0) {
        return '0'
    }
    if (cost.cost.audio === undefined) {
        warnMissingModalityRate(event, cost, 'audio')
        return bigDecimal.multiply(cost.cost.prompt_token, audioInputTokens)
    }
    return bigDecimal.multiply(cost.cost.audio, audioInputTokens)
}

const computeImageInputCost = (event: PluginEvent, cost: ResolvedModelCost, imageInputTokens: number): string => {
    if (imageInputTokens <= 0) {
        return '0'
    }
    if (cost.cost.image === undefined) {
        warnMissingModalityRate(event, cost, 'image')
        return bigDecimal.multiply(cost.cost.prompt_token, imageInputTokens)
    }
    return bigDecimal.multiply(cost.cost.image, imageInputTokens)
}

export const calculateInputCost = (event: PluginEvent, cost: ResolvedModelCost): string => {
    if (!event.properties) {
        return '0'
    }

    const exclusive = resolveCacheReportingExclusive(event)
    event.properties['$ai_cache_reporting_exclusive'] = exclusive

    const inputTokens = numericProperty(event, '$ai_input_tokens')
    const cacheReadTokens = numericProperty(event, '$ai_cache_read_input_tokens')
    const audioInputTokens = numericProperty(event, '$ai_audio_input_tokens')
    const imageInputTokens = numericProperty(event, '$ai_image_input_tokens')

    // Audio/image input tokens are reported by providers (OpenAI, Gemini) as a subset
    // of the total input token count. We bill them separately at modality rates and
    // subtract them from the text pool to avoid double-counting at the prompt rate.
    const audioInputCost = computeAudioInputCost(event, cost, audioInputTokens)
    const imageInputCost = computeImageInputCost(event, cost, imageInputTokens)
    const modalityInputCost = bigDecimal.add(audioInputCost, imageInputCost)
    const hasModalityTokens = audioInputTokens > 0 || imageInputTokens > 0

    if (matchProvider(event, 'anthropic')) {
        const cacheWriteTokens = numericProperty(event, '$ai_cache_creation_input_tokens')

        const writeCost =
            cost.cost.cache_write_token !== undefined
                ? bigDecimal.multiply(cost.cost.cache_write_token, cacheWriteTokens)
                : bigDecimal.multiply(bigDecimal.multiply(cost.cost.prompt_token, 1.25), cacheWriteTokens)

        const cacheReadCost =
            cost.cost.cache_read_token !== undefined
                ? bigDecimal.multiply(cost.cost.cache_read_token, cacheReadTokens)
                : bigDecimal.multiply(bigDecimal.multiply(cost.cost.prompt_token, 0.1), cacheReadTokens)

        const totalCacheCost = bigDecimal.add(writeCost, cacheReadCost)
        const baseUncachedTokens = exclusive
            ? inputTokens
            : bigDecimal.subtract(bigDecimal.subtract(inputTokens, cacheReadTokens), cacheWriteTokens)
        const uncachedTextTokens = clampTextTokens(
            bigDecimal.subtract(bigDecimal.subtract(baseUncachedTokens, audioInputTokens), imageInputTokens),
            hasModalityTokens
        )
        const uncachedCost = bigDecimal.multiply(cost.cost.prompt_token, uncachedTextTokens)

        return bigDecimal.add(bigDecimal.add(totalCacheCost, uncachedCost), modalityInputCost)
    }

    const baseRegularTokens = exclusive ? inputTokens : bigDecimal.subtract(inputTokens, cacheReadTokens)
    const regularTextTokens = clampTextTokens(
        bigDecimal.subtract(bigDecimal.subtract(baseRegularTokens, audioInputTokens), imageInputTokens),
        hasModalityTokens
    )

    let cacheReadCost: string

    if (cost.cost.cache_read_token !== undefined) {
        // Use explicit cache read cost if available
        cacheReadCost = bigDecimal.multiply(cost.cost.cache_read_token, cacheReadTokens)
    } else {
        // Use default multiplier of 0.5 for all providers when cache_read_token is not defined
        const multiplier = 0.5

        if (cacheReadTokens > 0) {
            logger.warn('Using default cache read multiplier for model', {
                multiplier,
                model: cost.model,
                provider: event.properties['$ai_provider'] || 'unknown',
            })
        }

        cacheReadCost = bigDecimal.multiply(bigDecimal.multiply(cost.cost.prompt_token, multiplier), cacheReadTokens)
    }

    const regularCost = bigDecimal.multiply(cost.cost.prompt_token, regularTextTokens)

    return bigDecimal.add(bigDecimal.add(cacheReadCost, regularCost), modalityInputCost)
}
