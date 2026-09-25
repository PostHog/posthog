/**
 * How a failed metric query on the experiment results page is classified. The page reacts to two
 * conditions that are not defects in the metric, so neither should reach the red error state.
 */

/** A metric query that failed, as `loadMetrics` in `experimentLogic` records it. */
export interface MetricQueryError {
    code?: string | null
    statusCode?: number | null
}

/**
 * `split_baseline_and_test_variants` (products/experiments/backend/hogql_queries/utils.py) raises
 * this when the baseline variant has no exposures yet. That is the normal state in the first
 * minutes of an experiment, so the page waits rather than reporting an error.
 */
export const NO_EXPOSURES_ERROR_CODE = 'no_data'

/** `ExperimentMetricAtCapacity` (products/experiments/backend/hogql_queries/error_handling.py). */
export const METRIC_RATE_LIMITED_ERROR_CODE = 'experiment_metric_rate_limited'

export function isNoExposuresError(error: MetricQueryError | null | undefined): boolean {
    return error?.code === NO_EXPOSURES_ERROR_CODE
}

/**
 * Capacity pressure the server asks us to come back from, not a fault in the metric. Two signals,
 * because the two producers sit on opposite sides of the query runner: the runner labels what it
 * catches with the code above, while the per-team query concurrency limiter refuses the request
 * before the runner starts and answers with a plain DRF 429.
 */
export function isCapacityError(error: MetricQueryError | null | undefined): boolean {
    return error?.code === METRIC_RATE_LIMITED_ERROR_CODE || error?.statusCode === 429
}
