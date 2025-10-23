import bigDecimal from 'js-big-decimal'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { logger } from '../../utils/logger'
import { ResolvedModelCost } from './providers/types'

const matchProvider = (event: PluginEvent, provider: string): boolean => {
    if (!event.properties) {
        return false
    }

    const { $ai_provider: eventProvider, $ai_model: eventModel } = event.properties
    const normalizedProvider = provider.toLowerCase()

    return eventProvider?.toLowerCase() === normalizedProvider || eventModel?.toLowerCase().includes(normalizedProvider)
}

export const calculateInputCost = (event: PluginEvent, cost: ResolvedModelCost): string => {
    if (!event.properties) {
        return '0'
    }

    const cacheReadTokens = event.properties['$ai_cache_read_input_tokens'] || 0
    const inputTokens = event.properties['$ai_input_tokens'] || 0

    // Anthropic special case: inputTokens already excludes cache tokens
    if (matchProvider(event, 'anthropic')) {
        const cacheWriteTokens = event.properties['$ai_cache_creation_input_tokens'] || 0

        // Use actual cache costs if available, otherwise fall back to multipliers
        const writeCost =
            cost.cost.cache_write_token !== undefined
                ? bigDecimal.multiply(cost.cost.cache_write_token, cacheWriteTokens)
                : bigDecimal.multiply(bigDecimal.multiply(cost.cost.prompt_token, 1.25), cacheWriteTokens)

        const cacheReadCost =
            cost.cost.cache_read_token !== undefined
                ? bigDecimal.multiply(cost.cost.cache_read_token, cacheReadTokens)
                : bigDecimal.multiply(bigDecimal.multiply(cost.cost.prompt_token, 0.1), cacheReadTokens)

        const totalCacheCost = bigDecimal.add(writeCost, cacheReadCost)
        const uncachedCost = bigDecimal.multiply(cost.cost.prompt_token, inputTokens)

        return bigDecimal.add(totalCacheCost, uncachedCost)
    }

    // Default case: inputTokens includes cache tokens, so subtract them
    // This applies to OpenAI, Gemini, and all other providers by default
    const regularTokens = bigDecimal.subtract(inputTokens, cacheReadTokens)

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

    const regularCost = bigDecimal.multiply(cost.cost.prompt_token, regularTokens)

    return bigDecimal.add(cacheReadCost, regularCost)
}
