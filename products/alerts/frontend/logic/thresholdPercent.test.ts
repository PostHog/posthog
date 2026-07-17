import { InsightThresholdType } from '~/queries/schema/schema-general'

import { fractionToPercentInput, rescaleFunnelBound } from './thresholdPercent'

describe('thresholdPercent', () => {
    // Stored 0–1 fractions render as percentage inputs without float noise — guards the ×100
    // round-trip surfacing values like 7.000000000000001 (regresses if the rounding is dropped).
    it.each([
        [undefined, undefined],
        [0.99, 99],
        [0.077, 7.7],
        [0.3333, 33.33],
        [1, 100],
    ])('fractionToPercentInput(%p) === %p', (fraction, expected) => {
        expect(fractionToPercentInput(fraction)).toBe(expected)
    })

    // Flipping a funnel's condition flips the threshold unit; the bound must rescale so the on-screen
    // number is preserved (regresses to a ×100 blowup — 99 → 9900 — if the rescale is dropped).
    it.each([
        [99, InsightThresholdType.PERCENTAGE, 0.99],
        [0.99, InsightThresholdType.ABSOLUTE, 99],
        [7, InsightThresholdType.PERCENTAGE, 0.07],
        [undefined, InsightThresholdType.PERCENTAGE, undefined],
    ])('rescaleFunnelBound(%p, %s) === %p', (value, toType, expected) => {
        expect(rescaleFunnelBound(value as number | undefined, toType)).toBe(expected)
    })

    it('preserves the displayed number across a unit switch instead of ×100-ing it', () => {
        // Entered as "99%" under a has-value (ABSOLUTE) condition, then switched to relative.
        const asFraction = rescaleFunnelBound(99, InsightThresholdType.PERCENTAGE)
        expect(fractionToPercentInput(asFraction)).toBe(99) // was 9900 before the fix
    })
})
