import bigDecimal from 'js-big-decimal'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { ResolvedModelCost } from './providers/types'

const REASONING_COST_MODELS = [/^gemini-2.5-/]

const mustAddReasoningCost = (model: string): boolean => {
    return REASONING_COST_MODELS.some((candidate) => candidate.test(model.toLowerCase()))
}

/**
 * Calculate output cost, including image output tokens if present.
 *
 * For multimodal models like Gemini with image generation:
 * - If $ai_image_output_tokens is present and image_output pricing exists,
 *   calculate image cost separately at the image output rate.
 * - Text output tokens are calculated at the standard completion rate.
 *
 * Example for gemini-2.5-flash-image:
 * - Text output: $2.50/1M tokens
 * - Image output: $30/1M tokens (1290 tokens per image = $0.039/image)
 */
export const calculateOutputCost = (event: PluginEvent, cost: ResolvedModelCost): string => {
    if (!event.properties) {
        return '0'
    }

    const imageOutputTokens = event.properties['$ai_image_output_tokens']
    const hasImageTokens = typeof imageOutputTokens === 'number' && imageOutputTokens > 0
    const hasImagePricing = cost.cost.image_output !== undefined && cost.cost.image_output > 0

    // If we have image tokens and image pricing, calculate costs separately
    if (hasImageTokens && hasImagePricing) {
        // Calculate image output cost
        const imageCost = bigDecimal.multiply(cost.cost.image_output!, imageOutputTokens)

        // Calculate text output cost
        // If we have explicit text tokens, use those; otherwise use total - image
        let textOutputTokens = event.properties['$ai_text_output_tokens']
        if (textOutputTokens === undefined) {
            const totalOutputTokens = event.properties['$ai_output_tokens'] || 0
            textOutputTokens = Math.max(0, Number(totalOutputTokens) - imageOutputTokens)
        }

        // Add reasoning tokens to text tokens for Gemini 2.5 models
        if (
            event.properties['$ai_reasoning_tokens'] &&
            event.properties['$ai_model'] &&
            mustAddReasoningCost(event.properties['$ai_model'])
        ) {
            textOutputTokens = bigDecimal.add(textOutputTokens, event.properties['$ai_reasoning_tokens'])
        }

        const textCost = bigDecimal.multiply(cost.cost.completion_token, textOutputTokens)

        return bigDecimal.add(imageCost, textCost)
    }

    // Standard path: no image tokens or no image pricing
    let outputTokens = event.properties['$ai_output_tokens'] || 0

    if (
        event.properties['$ai_reasoning_tokens'] &&
        event.properties['$ai_model'] &&
        mustAddReasoningCost(event.properties['$ai_model'])
    ) {
        outputTokens = bigDecimal.add(outputTokens, event.properties['$ai_reasoning_tokens'])
    }

    return bigDecimal.multiply(cost.cost.completion_token, outputTokens)
}
