import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { NodeStats } from '../types'

export function formatCostUsd(costUsd: number): string {
    if (costUsd === 0) {
        return '$0'
    }
    if (costUsd < 0.001) {
        return '<$0.001'
    }
    if (costUsd < 0.01) {
        return `$${Number(costUsd.toPrecision(2))}`
    }
    if (costUsd < 1) {
        return `$${costUsd.toFixed(2)}`
    }
    return `$${humanFriendlyNumber(costUsd, 2, 2)}`
}

export function formatLatencyMs(latencyMs: number): string {
    if (latencyMs < 1000) {
        return `${Math.round(latencyMs)}ms`
    }
    if (latencyMs < 60_000) {
        return `${humanFriendlyNumber(latencyMs / 1000, 2)}s`
    }
    return humanFriendlyDuration(latencyMs / 1000, { maxUnits: 2 })
}

export function formatTokens(inputTokens: number | null, outputTokens: number | null): string | null {
    if (inputTokens !== null && outputTokens !== null) {
        return `${humanFriendlyNumber(inputTokens, 0)} → ${humanFriendlyNumber(outputTokens, 0)} tok`
    }
    const known = inputTokens ?? outputTokens
    return known === null ? null : `${humanFriendlyNumber(known, 0)} tok`
}

export function statParts(stats: NodeStats): string[] {
    const tokens = formatTokens(stats.inputTokens, stats.outputTokens)
    return [
        stats.costUsd !== null ? formatCostUsd(stats.costUsd) : null,
        tokens,
        stats.latencyMs !== null ? formatLatencyMs(stats.latencyMs) : null,
        stats.cacheReadTokens ? `${humanFriendlyNumber(stats.cacheReadTokens, 0)} cached` : null,
    ].filter((part): part is string => part !== null)
}

export function compactStatParts(stats: NodeStats): string[] {
    const knownTokens = [stats.inputTokens, stats.outputTokens].filter((count): count is number => count !== null)
    return [
        stats.latencyMs !== null ? formatLatencyMs(stats.latencyMs) : null,
        knownTokens.length > 0
            ? `${humanFriendlyNumber(
                  knownTokens.reduce((a, b) => a + b, 0),
                  0
              )} tok`
            : null,
    ].filter((part): part is string => part !== null)
}
