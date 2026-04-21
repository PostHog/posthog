// Indicator group and indicator name constants shared across pipelines.
//
// An **indicator group** defines a measurement shape backed by a single
// Prometheus histogram: its metric name, unit, buckets, and help text.
// Multiple indicators of the same group share that histogram (keyed by the
// `sli` label).
//
// Different groups have independent histograms, so they can have independent
// bucket sets — use separate groups when measurements need different buckets.
//
// To add a new indicator: add a constant + type alias here and extend
// `IndicatorName`. If its measurement shape doesn't fit an existing group,
// also add a new `IndicatorGroup` constant.

/**
 * Metric-level definition of an indicator group.
 *
 * `name` is used verbatim as the Prometheus metric name — stick to the
 * `ingestion_sli_<family>_<unit>_histogram` convention so the shared
 * Grafana panel can discover all SLI metrics via `__name__=~...` regex.
 */
export interface IndicatorGroup<B extends readonly number[]> {
    name: string
    help: string
    unit: 'ms'
    buckets: B
}

export const INGESTION_LATENCY_GROUP = {
    name: 'ingestion_sli_ingestion_latency_ms_histogram',
    help: 'Latency of ingestion stages, in ms',
    unit: 'ms',
    buckets: [1000, 2000, 5000, 10000, 30000, 60000, 120000, 300000, 600000, 900000],
} as const satisfies IndicatorGroup<readonly number[]>
export type IngestionLatencyGroup = typeof INGESTION_LATENCY_GROUP

export const INGESTION_LAG_INDICATOR = 'ingestion_lag' as const
export type IngestionLagIndicator = typeof INGESTION_LAG_INDICATOR

/** Union of all known SLI names. Extend as new indicators are added. */
export type IndicatorName = IngestionLagIndicator

export const OBJECTIVE_KIND = 'objective' as const
export type ObjectiveKind = typeof OBJECTIVE_KIND

export const AGREEMENT_KIND = 'agreement' as const
export type AgreementKind = typeof AGREEMENT_KIND

export type SlaKind = ObjectiveKind | AgreementKind
