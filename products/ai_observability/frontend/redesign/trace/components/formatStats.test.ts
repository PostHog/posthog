import { compactStatParts, formatCostUsd, formatLatencyMs, formatTokenCounts, statParts } from './formatStats'

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

    it('omits unknown stats instead of rendering them as zero', () => {
        expect(
            statParts({ costUsd: null, inputTokens: null, outputTokens: null, cacheReadTokens: null, latencyMs: 90 })
        ).toEqual(['90ms'])
        expect(
            statParts({ costUsd: 0, inputTokens: 10, outputTokens: 5, cacheReadTokens: 8, latencyMs: null })
        ).toEqual(['$0', '10 in · 5 out', '8 cached'])
        expect(
            compactStatParts({ costUsd: 0, inputTokens: 10, outputTokens: 5, cacheReadTokens: 8, latencyMs: null })
        ).toEqual(['15 tok'])
    })
})
