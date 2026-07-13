import { InsightThresholdType } from '~/queries/schema/schema-general'

// PERCENTAGE thresholds are stored as a 0–1 fraction and shown ×100; ABSOLUTE ones store the raw
// percent. These helpers keep the on-screen number stable across that boundary and round the
// round-trip so it doesn't surface floating-point noise (e.g. 7.000000000000001).

const roundPercent = (value: number): number => Math.round(value * 1e6) / 1e6

/** Render a stored 0–1 fraction as a percentage input value, rounded to avoid float noise. */
export const fractionToPercentInput = (fraction: number | undefined): number | undefined =>
    typeof fraction === 'number' ? roundPercent(fraction * 100) : undefined

/** Convert a bound between the relative (0–1 fraction, PERCENTAGE) and absolute (raw percent) units so
 * the displayed number is preserved when a funnel's condition flips the threshold type — rather than
 * jumping ×100 / ÷100. */
export const rescaleFunnelBound = (value: number | undefined, toType: InsightThresholdType): number | undefined => {
    if (typeof value !== 'number') {
        return undefined
    }
    return toType === InsightThresholdType.PERCENTAGE ? roundPercent(value / 100) : roundPercent(value * 100)
}
