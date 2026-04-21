import { Gauge, Histogram, register } from 'prom-client'

const SLA_TARGET_GAUGE_NAME = 'ingestion_slo_target_ratio'

/**
 * Get or create the histogram backing one indicator type.
 *
 * Named after the type. Buckets are locked in on first creation — a second
 * call with the same name returns the existing registration regardless of
 * the buckets argument.
 */
export function getOrCreateSliHistogram(
    name: string,
    help: string,
    buckets: readonly number[]
): Histogram<'pipeline' | 'lane' | 'sli'> {
    const existing = register.getSingleMetric(name)
    if (existing) {
        return existing as Histogram<'pipeline' | 'lane' | 'sli'>
    }
    return new Histogram({
        name,
        help,
        labelNames: ['pipeline', 'lane', 'sli'],
        buckets: [...buckets],
    })
}

/**
 * Get or create the shared target ratio gauge.
 *
 * One time series per (pipeline, lane, sli, name, kind, le). Value is the
 * target compliance ratio (e.g. 0.999). `le` mirrors a histogram's bucket
 * label so Grafana can join target→bucket on `on(pipeline, lane, sli, le)`.
 */
export function getOrCreateSlaTargetGauge(): Gauge<'pipeline' | 'lane' | 'sli' | 'name' | 'kind' | 'le'> {
    const existing = register.getSingleMetric(SLA_TARGET_GAUGE_NAME)
    if (existing) {
        return existing as Gauge<'pipeline' | 'lane' | 'sli' | 'name' | 'kind' | 'le'>
    }
    return new Gauge({
        name: SLA_TARGET_GAUGE_NAME,
        help: 'Declared SLO/SLA target compliance ratio per indicator and threshold',
        labelNames: ['pipeline', 'lane', 'sli', 'name', 'kind', 'le'],
    })
}
