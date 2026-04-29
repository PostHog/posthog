import bigDecimal from 'js-big-decimal'

import { PluginEvent } from '~/plugin-scaffold'

import { numericProperty } from './modality-tokens'
import { ResolvedModelCost } from './providers/types'

const REASONING_COST_MODELS = [/^gemini-2\.5-/, /^gemini-3(\.\d+)?-/]

const mustAddReasoningCost = (model: string): boolean => {
    return REASONING_COST_MODELS.some((candidate) => candidate.test(model.toLowerCase()))
}

export interface OutputModalityCost {
    audio: string
    image: string
}

const computeAudioOutputCost = (event: PluginEvent, cost: ResolvedModelCost): string => {
    const audioTokens = numericProperty(event, '$ai_audio_output_tokens')
    if (audioTokens <= 0) {
        return '0'
    }
    const rate = cost.cost.audio_output ?? cost.cost.completion_token
    return bigDecimal.multiply(rate, audioTokens)
}

const computeImageOutputCost = (event: PluginEvent, cost: ResolvedModelCost): string => {
    const imageTokens = numericProperty(event, '$ai_image_output_tokens')
    if (imageTokens <= 0) {
        return '0'
    }
    const rate = cost.cost.image_output ?? cost.cost.completion_token
    return bigDecimal.multiply(rate, imageTokens)
}

export const calculateOutputModalityCosts = (event: PluginEvent, cost: ResolvedModelCost): OutputModalityCost => {
    if (!event.properties) {
        return { audio: '0', image: '0' }
    }
    return {
        audio: computeAudioOutputCost(event, cost),
        image: computeImageOutputCost(event, cost),
    }
}

/**
 * Calculate output cost. Audio and image output tokens are billed at their
 * dedicated rates when the model exposes them, falling back to the standard
 * completion rate otherwise. Modality tokens are subtracted from the text pool
 * to avoid double-counting.
 *
 * Reasoning tokens are added to the text pool for Gemini 2.5/3 — those models
 * report reasoning separately but still bill it at the completion rate.
 *
 * Example for gemini-2.5-flash-image:
 * - Text output: $2.50/1M tokens
 * - Image output: $30/1M tokens (1290 tokens per image = $0.039/image)
 *
 * Example for gpt-4o-audio-preview:
 * - Text output: $10/1M tokens
 * - Audio output: $80/1M tokens
 */
export const calculateOutputCost = (event: PluginEvent, cost: ResolvedModelCost): string => {
    if (!event.properties) {
        return '0'
    }

    const audioOutputTokens = numericProperty(event, '$ai_audio_output_tokens')
    const imageOutputTokens = numericProperty(event, '$ai_image_output_tokens')

    const audioOutputCost = computeAudioOutputCost(event, cost)
    const imageOutputCost = computeImageOutputCost(event, cost)
    const modalityOutputCost = bigDecimal.add(audioOutputCost, imageOutputCost)

    const totalOutputTokens = numericProperty(event, '$ai_output_tokens')
    const explicitTextOutputTokens = event.properties['$ai_text_output_tokens']

    let textOutputTokens: number | string
    if (typeof explicitTextOutputTokens === 'number') {
        textOutputTokens = explicitTextOutputTokens
    } else {
        const derived = totalOutputTokens - audioOutputTokens - imageOutputTokens
        // Clamp to 0 when modality tokens exceed total, otherwise preserve sign
        // for the legacy "negative output tokens" code path that flows through here.
        textOutputTokens = audioOutputTokens > 0 || imageOutputTokens > 0 ? Math.max(0, derived) : derived
    }

    const reasoningTokens = event.properties['$ai_reasoning_tokens']
    if (reasoningTokens && event.properties['$ai_model'] && mustAddReasoningCost(event.properties['$ai_model'])) {
        textOutputTokens = bigDecimal.add(textOutputTokens, reasoningTokens)
    }

    const textCost = bigDecimal.multiply(cost.cost.completion_token, textOutputTokens)

    return bigDecimal.add(textCost, modalityOutputCost)
}
