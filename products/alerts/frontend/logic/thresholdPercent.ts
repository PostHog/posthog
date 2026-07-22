import { AlertConditionType, InsightThreshold, InsightThresholdType } from '~/queries/schema/schema-general'

// PERCENTAGE thresholds are stored as a 0–1 fraction and shown ×100; ABSOLUTE ones store the raw
// percent. These helpers keep the on-screen number stable across that boundary and round the
// round-trip so it doesn't surface floating-point noise (e.g. 7.000000000000001).

const roundPercent = (value: number): number => Math.round(value * 1e6) / 1e6

/** Render a stored 0–1 fraction as a percentage input value, rounded to avoid float noise. */
export const fractionToPercentInput = (fraction: number | undefined): number | undefined =>
    typeof fraction === 'number' ? roundPercent(fraction * 100) : undefined

export const inputToStoredBound = (value: number | undefined, type: InsightThresholdType): number | undefined => {
    if (value === undefined || Number.isNaN(value)) {
        return undefined
    }
    return type === InsightThresholdType.PERCENTAGE ? value / 100 : value
}

/** Convert a bound between the relative (0–1 fraction, PERCENTAGE) and absolute (raw) units. */
export const rescaleThresholdBound = (value: number | undefined, toType: InsightThresholdType): number | undefined => {
    if (typeof value !== 'number') {
        return undefined
    }
    return toType === InsightThresholdType.PERCENTAGE ? roundPercent(value / 100) : roundPercent(value * 100)
}

export function thresholdForUnitChange(
    configuration: InsightThreshold,
    targetType: InsightThresholdType
): InsightThreshold {
    if (configuration.type === targetType) {
        return configuration
    }

    return {
        type: targetType,
        bounds: {
            lower: rescaleThresholdBound(configuration.bounds?.lower, targetType),
            upper: rescaleThresholdBound(configuration.bounds?.upper, targetType),
        },
    }
}

export function thresholdForConditionChange(
    configuration: InsightThreshold,
    conditionType: AlertConditionType,
    forcePercentageForRelative: boolean
): InsightThreshold {
    let targetType = configuration.type
    if (conditionType === AlertConditionType.ABSOLUTE_VALUE) {
        targetType = InsightThresholdType.ABSOLUTE
    } else if (forcePercentageForRelative) {
        targetType = InsightThresholdType.PERCENTAGE
    }

    if (configuration.type === targetType) {
        return configuration
    }

    return thresholdForUnitChange(configuration, targetType)
}
