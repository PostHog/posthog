import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { TraceApi, TraceNodeStatsApi } from '../../../generated/api.schemas'
import { formatCostUsd } from '../../shared/formatCost'

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

export type StatKind = 'cost' | 'tokens' | 'latency' | 'cacheRead' | 'cacheWrite'

export interface StatPart {
    kind: StatKind
    text: string
}

function knownParts(parts: [StatKind, string | null][]): StatPart[] {
    return parts.flatMap(([kind, text]) => (text !== null ? [{ kind, text }] : []))
}

export function statParts(stats: TraceNodeStatsApi): StatPart[] {
    return knownParts([
        ['cost', stats.costUsd !== null ? formatCostUsd(stats.costUsd) : null],
        ['tokens', formatTokenCounts(stats.inputTokens, stats.outputTokens)],
        ['latency', stats.latencyMs !== null ? formatLatencyMs(stats.latencyMs) : null],
        ['cacheRead', stats.cacheReadTokens ? `${humanFriendlyNumber(stats.cacheReadTokens, 0)} cache read` : null],
        ['cacheWrite', stats.cacheWriteTokens ? `${humanFriendlyNumber(stats.cacheWriteTokens, 0)} cache write` : null],
    ])
}

export function compactStatParts(stats: TraceNodeStatsApi): StatPart[] {
    const knownTokens = [stats.inputTokens, stats.outputTokens].filter((count): count is number => count !== null)
    return knownParts([
        ['latency', stats.latencyMs !== null ? formatLatencyMs(stats.latencyMs) : null],
        [
            'tokens',
            knownTokens.length > 0
                ? `${humanFriendlyNumber(
                      knownTokens.reduce((a, b) => a + b, 0),
                      0
                  )} tok`
                : null,
        ],
    ])
}

const TOTALS_KINDS: StatKind[] = ['tokens', 'cacheRead', 'cacheWrite']
const COST_AND_LATENCY_KINDS: StatKind[] = ['cost', 'latency']

/** The stats of a trace's overview that were computed from only some of its steps. */
export function partialStatKinds({
    totalsPartial,
    costAndLatencyPartial,
}: Pick<TraceApi, 'totalsPartial' | 'costAndLatencyPartial'>): StatKind[] {
    return [...(totalsPartial ? TOTALS_KINDS : []), ...(costAndLatencyPartial ? COST_AND_LATENCY_KINDS : [])]
}
