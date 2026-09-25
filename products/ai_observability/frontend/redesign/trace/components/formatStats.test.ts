import { compactStatParts, formatCostUsd, formatLatencyMs, formatTokens, statParts } from './formatStats'

describe('formatStats', () => {
    it.each([
        [0, '$0'],
        [0.0004, '<$0.001'],
        [0.0034, '$0.0034'],
        [0.5, '$0.50'],
        [0.999, '$1.00'],
        [1.5, '$1.50'],
    ])('formats cost %p as %p', (cost, expected) => {
        expect(formatCostUsd(cost)).toBe(expected)
    })

    it.each([
        [420, '420ms'],
        [1840, '1.84s'],
        [754_000, '12m\u00a034s'],
    ])('formats latency %p as %p', (ms, expected) => {
        expect(formatLatencyMs(ms)).toBe(expected)
    })

    it('shows input and output tokens as a flow, or one side when the other is unknown', () => {
        expect(formatTokens(2180, 266)).toBe('2,180 → 266 tok')
        expect(formatTokens(128, null)).toBe('128 tok')
        expect(formatTokens(null, null)).toBeNull()
    })

    it('omits unknown stats instead of rendering them as zero', () => {
        expect(
            statParts({ costUsd: null, inputTokens: null, outputTokens: null, cacheReadTokens: null, latencyMs: 90 })
        ).toEqual(['90ms'])
        expect(
            statParts({ costUsd: 0, inputTokens: 10, outputTokens: 5, cacheReadTokens: 8, latencyMs: null })
        ).toEqual(['$0', '10 → 5 tok', '8 cached'])
        expect(
            compactStatParts({ costUsd: 0, inputTokens: 10, outputTokens: 5, cacheReadTokens: 8, latencyMs: null })
        ).toEqual(['15 tok'])
    })
})
