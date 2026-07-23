import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import {
    fractionToPercentInput,
    inputToStoredBound,
    rescaleThresholdBound,
    thresholdForConditionChange,
    thresholdForUnitChange,
} from './thresholdPercent'

describe('thresholdPercent', () => {
    it.each([
        [undefined, InsightThresholdType.ABSOLUTE, undefined],
        [NaN, InsightThresholdType.ABSOLUTE, undefined],
        [100, InsightThresholdType.ABSOLUTE, 100],
        [100, InsightThresholdType.PERCENTAGE, 1],
    ])('stores input %p with %s units as %p', (value, type, expected) => {
        expect(inputToStoredBound(value, type)).toBe(expected)
    })

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
    ])('rescaleThresholdBound(%p, %s) === %p', (value, toType, expected) => {
        expect(rescaleThresholdBound(value as number | undefined, toType)).toBe(expected)
    })

    it('preserves the displayed number across a unit switch instead of ×100-ing it', () => {
        // Entered as "99%" under a has-value (ABSOLUTE) condition, then switched to relative.
        const asFraction = rescaleThresholdBound(99, InsightThresholdType.PERCENTAGE)
        expect(fractionToPercentInput(asFraction)).toBe(99) // was 9900 before the fix
    })

    it.each([
        [
            InsightThresholdType.PERCENTAGE,
            { lower: 0.1, upper: 0.25 },
            InsightThresholdType.ABSOLUTE,
            { lower: 10, upper: 25 },
        ],
        [
            InsightThresholdType.ABSOLUTE,
            { lower: 10, upper: 25 },
            InsightThresholdType.PERCENTAGE,
            { lower: 0.1, upper: 0.25 },
        ],
    ])('preserves displayed bounds when switching from %s to %s', (fromType, bounds, toType, expectedBounds) => {
        expect(thresholdForUnitChange({ type: fromType, bounds }, toType)).toEqual({
            type: toType,
            bounds: expectedBounds,
        })
    })

    it('preserves displayed percentage values when switching to an absolute condition', () => {
        expect(
            thresholdForConditionChange(
                {
                    type: InsightThresholdType.PERCENTAGE,
                    bounds: { lower: 0.2, upper: 3 },
                },
                AlertConditionType.ABSOLUTE_VALUE,
                false
            )
        ).toEqual({
            type: InsightThresholdType.ABSOLUTE,
            bounds: { lower: 20, upper: 300 },
        })
    })
})
