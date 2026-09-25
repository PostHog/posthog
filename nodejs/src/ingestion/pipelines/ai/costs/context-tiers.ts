import { PluginEvent } from '~/plugin-scaffold'

import { finiteNumberOrUndefined, numericProperty } from './cost-utils'
import { resolveCacheReportingExclusive } from './input-costs'
import type { ContextLengthTier, ResolvedModelCost } from './providers/types'

const cacheWriteTokens = (event: PluginEvent): number => {
    const has = (key: string): boolean => finiteNumberOrUndefined(event.properties?.[key]) !== undefined
    if (has('$ai_cache_creation_5m_input_tokens') && has('$ai_cache_creation_1h_input_tokens')) {
        return (
            numericProperty(event, '$ai_cache_creation_5m_input_tokens') +
            numericProperty(event, '$ai_cache_creation_1h_input_tokens')
        )
    }
    return numericProperty(event, '$ai_cache_creation_input_tokens')
}

/**
 * The prompt length a vendor's context threshold compares against: every token
 * the request sent, cached or not. Providers that report input tokens exclusive
 * of the cache pools leave those tokens out of `$ai_input_tokens`, so add them
 * back — otherwise a mostly cached million-token prompt reads as a short one.
 */
export const promptTokensForTier = (event: PluginEvent): number => {
    const inputTokens = numericProperty(event, '$ai_input_tokens')
    if (!event.properties) {
        return inputTokens
    }

    // Persist the verdict: resolving it counts a metric, and `calculateInputCost`
    // reads the property back rather than deciding the same event twice.
    const exclusive = resolveCacheReportingExclusive(event)
    event.properties['$ai_cache_reporting_exclusive'] = exclusive
    if (!exclusive) {
        return inputTokens
    }

    return inputTokens + numericProperty(event, '$ai_cache_read_input_tokens') + cacheWriteTokens(event)
}

const highestApplicableTier = (tiers: ContextLengthTier[], promptTokens: number): ContextLengthTier | undefined => {
    let selected: ContextLengthTier | undefined
    for (const tier of tiers) {
        if (promptTokens > tier.min_input_tokens && (!selected || tier.min_input_tokens > selected.min_input_tokens)) {
            selected = tier
        }
    }
    return selected
}

/**
 * Swap in the long-context rates a model charges for this prompt length. Every
 * rate the tier names wins, so cache and modality rates move with the text
 * rates, and output bills at the long-context rate too — vendors raise it on the
 * same threshold.
 */
export const applyContextTier = (cost: ResolvedModelCost, promptTokens: number): ResolvedModelCost => {
    const tiers = cost.cost.context_tiers
    if (!tiers?.length) {
        return cost
    }

    const tier = highestApplicableTier(tiers, promptTokens)
    if (!tier) {
        return cost
    }

    const tieredCost = { ...cost.cost }
    for (const [field, rate] of Object.entries(tier)) {
        if (field !== 'min_input_tokens' && typeof rate === 'number') {
            tieredCost[field as keyof Omit<ContextLengthTier, 'min_input_tokens'>] = rate
        }
    }

    return { ...cost, cost: tieredCost }
}
