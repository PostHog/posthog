import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { NodeStats } from '../types'

const TRAILING_ZEROS_BEYOND_CENTS = /0{1,2}$/

export function formatCostUsd(costUsd: number): string {
    if (costUsd === 0) {
        return '$0'
    }
    if (costUsd < 0.001) {
        return '<$0.001'
    }
    if (costUsd < 1) {
        return `$${costUsd.toFixed(4).replace(TRAILING_ZEROS_BEYOND_CENTS, '')}`
    }
    return `$${humanFriendlyNumber(costUsd, 2, 2)}`
}

export function formatLatencyMs(latencyMs: number): string {
    const roundedMs = Math.round(latencyMs)
    if (roundedMs < 1000) {
        return `${roundedMs}ms`
    }
    // Rounds before picking a unit, so 59_996ms (~60s) renders as "1m", not "60s".
    const roundedSeconds = Math.round((roundedMs / 1000) * 100) / 100
    if (roundedSeconds < 60) {
        return `${humanFriendlyNumber(roundedSeconds, 2)}s`
    }
    return humanFriendlyDuration(roundedSeconds, { maxUnits: 2 })
}

export function formatTokenCounts(inputTokens: number | null, outputTokens: number | null): string | null {
    const sides = [
        inputTokens !== null ? `${humanFriendlyNumber(inputTokens, 0)} in` : null,
        outputTokens !== null ? `${humanFriendlyNumber(outputTokens, 0)} out` : null,
    ].filter((side): side is string => side !== null)
    return sides.length > 0 ? sides.join(' · ') : null
}

export function formatCacheTokens(readTokens: number | null, writeTokens: number | null): string | null {
    const sides = [
        readTokens ? `${humanFriendlyNumber(readTokens, 0)} read` : null,
        writeTokens ? `${humanFriendlyNumber(writeTokens, 0)} write` : null,
    ].filter((side): side is string => side !== null)
    return sides.length > 0 ? sides.join(' · ') : null
}

export function statParts(stats: NodeStats): string[] {
    const tokens = formatTokenCounts(stats.inputTokens, stats.outputTokens)
    return [
        stats.costUsd !== null ? formatCostUsd(stats.costUsd) : null,
        tokens,
        stats.latencyMs !== null ? formatLatencyMs(stats.latencyMs) : null,
        stats.cacheReadTokens ? `${humanFriendlyNumber(stats.cacheReadTokens, 0)} cache read` : null,
        stats.cacheWriteTokens ? `${humanFriendlyNumber(stats.cacheWriteTokens, 0)} cache write` : null,
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
