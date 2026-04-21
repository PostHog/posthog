/**
 * Objective/agreement target. The threshold picks one of the indicator
 * type's declared histogram buckets; the ratio is the fraction of events
 * that must fall under that bucket for the SLO to be met.
 */
export interface TargetSpec<B extends readonly number[]> {
    thresholdMs: B[number]
    /** Fraction in [0, 1], e.g. 0.999. */
    targetRatio: number
}

export interface IndicatorHandle {
    observe(valueMs: number): void
}
