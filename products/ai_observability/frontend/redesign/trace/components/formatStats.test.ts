import { NodeStats } from '../types'
import {
    compactStatParts,
    formatCacheTokens,
    formatCostUsd,
    formatLatencyMs,
    formatTokenCounts,
    statParts,
} from './formatStats'

describe('formatStats', () => {
    it.each([
        [0, '$0'],
        [0.0004, '<$0.001'],
        [0.0021, '$0.0021'],
        [0.0154, '$0.0154'],
        [0.1257, '$0.1257'],
        [0.5, '$0.50'],
        [0.999, '$0.999'],
        [1.5, '$1.50'],
    ])('formats cost %p as %p', (cost, expected) => {
        expect(formatCostUsd(cost)).toBe(expected)
    })

    it.each([
        [420, '420ms'],
        [1840, '1.84s'],
        [999.6, '1s'],
        [59_996, '1m'],
        [754_000, '12m\u00a034s'],
    ])('formats latency %p as %p', (ms, expected) => {
        expect(formatLatencyMs(ms)).toBe(expected)
    })

    it.each([
        [2180, 266, '2,180 in · 266 out'],
        [128, null, '128 in'],
        [null, 266, '266 out'],
        [null, null, null],
    ])('formats %p input and %p output tokens as %p', (inputTokens, outputTokens, expected) => {
        expect(formatTokenCounts(inputTokens, outputTokens)).toBe(expected)
    })

    it.each([
        [56210, 1585, '56,210 read · 1,585 write'],
        [1024, null, '1,024 read'],
        [null, 29, '29 write'],
        [0, 0, null],
        [null, null, null],
    ])('formats %p cache reads and %p cache writes as %p', (readTokens, writeTokens, expected) => {
        expect(formatCacheTokens(readTokens, writeTokens)).toBe(expected)
    })

    const unknownStats: NodeStats = {
        costUsd: null,
        inputTokens: null,
        outputTokens: null,
        cacheReadTokens: null,
        cacheWriteTokens: null,
        latencyMs: null,
    }

    it.each<[string, Partial<NodeStats>, string[]]>([
        ['latency only', { latencyMs: 90 }, ['90ms']],
        [
            'zero cost with cache reads and writes',
            { costUsd: 0, inputTokens: 10, outputTokens: 5, cacheReadTokens: 8, cacheWriteTokens: 3 },
            ['$0', '10 in · 5 out', '8 cache read', '3 cache write'],
        ],
        ['cache writes without reads', { cacheWriteTokens: 1585 }, ['1,585 cache write']],
    ])('statParts omits unknown stats for %s', (_label, stats, expected) => {
        expect(statParts({ ...unknownStats, ...stats })).toEqual(expected)
    })

    it.each<[string, Partial<NodeStats>, string[]]>([
        ['both token sides', { inputTokens: 10, outputTokens: 5, cacheReadTokens: 8 }, ['15 tok']],
        ['only input tokens', { inputTokens: 10 }, ['10 tok']],
        ['only output tokens', { outputTokens: 5, latencyMs: 420 }, ['420ms', '5 tok']],
        ['nothing known', {}, []],
    ])('compactStatParts with %s', (_label, stats, expected) => {
        expect(compactStatParts({ ...unknownStats, ...stats })).toEqual(expected)
    })
})
