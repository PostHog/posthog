import { COUNT_PER_ACTOR_MATH_DEFINITIONS, PROPERTY_MATH_DEFINITIONS } from 'scenes/trends/mathsLogic'

import { CountPerActorMathType, InsightType, PropertyMathType } from '~/types'

// Property math types that can be meaningfully aggregated when rolling up histogram buckets
// e.g. taking p99 of p99 values doesn't make sense
export const SUPPORTED_PROPERTY_MATH_FOR_HISTOGRAM_BREAKDOWN = new Set([
    PropertyMathType.Sum,
    PropertyMathType.Average,
    PropertyMathType.Minimum,
    PropertyMathType.Maximum,
])

export function isPropertyValueMath(math: string | undefined): math is PropertyMathType {
    return !!math && math in PROPERTY_MATH_DEFINITIONS
}

export function isCountPerActorMath(math: string | undefined): math is CountPerActorMathType {
    return !!math && math in COUNT_PER_ACTOR_MATH_DEFINITIONS
}

export function getDefaultPropertyMathType(
    math: string | undefined,
    allowedMathTypes: readonly string[] | undefined,
    isHistogramBreakdown?: boolean
): PropertyMathType {
    // Median isn't supported when rolling up histogram buckets, so fall back to average there
    const defaultMathType = isHistogramBreakdown ? PropertyMathType.Average : PropertyMathType.Median
    if (isPropertyValueMath(math)) {
        return math
    }
    if (allowedMathTypes?.length) {
        const propertyMathTypes = allowedMathTypes.filter(isPropertyValueMath)
        return (propertyMathTypes[0] as PropertyMathType) || defaultMathType
    }
    return defaultMathType
}

export function getDefaultMathHogQLExpression(insightType?: InsightType): string {
    return insightType === InsightType.STICKINESS ? 'person_id' : 'count()'
}
