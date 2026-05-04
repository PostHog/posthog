import bigDecimal from 'js-big-decimal'

import { PluginEvent } from '~/plugin-scaffold'

import { logger } from '../../../utils/logger'
import { numericProperty } from './cost-utils'
import { ResolvedModelCost } from './providers/types'

const REASONING_COST_MODELS = [/^gemini-2\.5-/, /^gemini-3(\.\d+)?-/]

const mustAddReasoningCost = (model: string): boolean => {
    return REASONING_COST_MODELS.some((candidate) => candidate.test(model.toLowerCase()))
}

const warnMissingModalityRate = (event: PluginEvent, cost: ResolvedModelCost, modality: 'audio' | 'image'): void => {
    logger.warn('Missing modality output rate; falling back to completion rate', {
        modality,
        model: cost.model,
        provider: event.properties?.['$ai_provider'] || 'unknown',
    })
}

const computeAudioOutputCost = (event: PluginEvent, cost: ResolvedModelCost, audioOutputTokens: number): string => {
    if (audioOutputTokens <= 0) {
        return '0'
    }
    if (cost.cost.audio_output === undefined) {
        warnMissingModalityRate(event, cost, 'audio')
        return bigDecimal.multiply(cost.cost.completion_token, audioOutputTokens)
    }
    return bigDecimal.multiply(cost.cost.audio_output, audioOutputTokens)
}

const computeImageOutputCost = (event: PluginEvent, cost: ResolvedModelCost, imageOutputTokens: number): string => {
    if (imageOutputTokens <= 0) {
        return '0'
    }
    if (cost.cost.image_output === undefined) {
        warnMissingModalityRate(event, cost, 'image')
        return bigDecimal.multiply(cost.cost.completion_token, imageOutputTokens)
    }
    return bigDecimal.multiply(cost.cost.image_output, imageOutputTokens)
}

/**
 * Calculate output cost. Audio and image output tokens are billed at their
 * dedicated rates when the model exposes them, falling back to the standard
 * completion rate otherwise (and emitting a warning so the missing rate is
 * visible). Modality tokens are subtracted from the text pool to avoid
 * double-counting.
 *
 * Reasoning tokens are added to the text pool for Gemini 2.5/3 — those models
 * report reasoning separately but still bill it at the completion rate.
 */
export const calculateOutputCost = (event: PluginEvent, cost: ResolvedModelCost): string => {
    if (!event.properties) {
        return '0'
    }

    const audioOutputTokens = numericProperty(event, '$ai_audio_output_tokens')
    const imageOutputTokens = numericProperty(event, '$ai_image_output_tokens')

    const audioOutputCost = computeAudioOutputCost(event, cost, audioOutputTokens)
    const imageOutputCost = computeImageOutputCost(event, cost, imageOutputTokens)
    const modalityOutputCost = bigDecimal.add(audioOutputCost, imageOutputCost)

    const rawTextOutputTokens = event.properties['$ai_text_output_tokens']
    const hasExplicitText = rawTextOutputTokens !== undefined && rawTextOutputTokens !== null

    let textOutputTokens: number | string
    if (hasExplicitText) {
        // Route through numericProperty so numeric strings ("100") still parse
        // but garbage ("abc") yields 0 instead of poisoning bigDecimal with NaN.
        textOutputTokens = numericProperty(event, '$ai_text_output_tokens')
    } else {
        const totalOutputTokens = numericProperty(event, '$ai_output_tokens')
        const derived = totalOutputTokens - audioOutputTokens - imageOutputTokens
        // Clamp to zero when modality tokens exceed the total output count.
        // Without modality tokens, negatives flow through so callers can spot
        // data-integrity issues via negative totals (some test fixtures rely on
        // this to assert behaviour against synthetic negative inputs).
        textOutputTokens = audioOutputTokens > 0 || imageOutputTokens > 0 ? Math.max(0, derived) : derived
    }

    const reasoningTokens = event.properties['$ai_reasoning_tokens']
    if (reasoningTokens && event.properties['$ai_model'] && mustAddReasoningCost(event.properties['$ai_model'])) {
        textOutputTokens = bigDecimal.add(textOutputTokens, reasoningTokens)
    }

    const textCost = bigDecimal.multiply(cost.cost.completion_token, textOutputTokens)

    return bigDecimal.add(textCost, modalityOutputCost)
}
