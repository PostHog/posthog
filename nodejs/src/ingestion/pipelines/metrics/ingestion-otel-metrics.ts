import { Attributes, Counter, metrics as metricsApi } from '@opentelemetry/api'

import { createCounterWithExemplars, swallowing } from '~/common/metrics/instruments'

/**
 * OTLP-pushed per-team ingestion counters, landing in the PostHog metrics product
 * through the exporter installed by initMetrics (common/metrics/otel-metrics.ts).
 * They answer "which teams are actually ingesting metrics" — a signal neither the
 * aggregate prom counters (no team label) nor the app_metrics2 usage rows (billing
 * store, not queryable as a metric) provide.
 *
 * Names mirror the app_metrics2 usage rows (records_ingested/bytes_ingested)
 * rather than the prom *_allowed_total counters, which already reach the metrics
 * product team-less via the scrape bridge — reusing those names would mix two
 * label schemas. The boundary here is stricter than the usage rows: recorded only
 * after a message is successfully produced to the ClickHouse-bound topic, so
 * DLQ'd messages never count as ingested.
 *
 * Instruments are acquired lazily on first record: the OTel metrics API has no proxy
 * provider, so instruments created at module load (before initMetrics runs) would be
 * bound to the noop meter forever.
 */

interface MetricsIngestionInstruments {
    bytesIngested: Counter
    recordsIngested: Counter
}

let instruments: MetricsIngestionInstruments | null = null

function getInstruments(): MetricsIngestionInstruments {
    if (instruments === null) {
        const meter = metricsApi.getMeter('metrics-ingestion')
        instruments = {
            bytesIngested: createCounterWithExemplars(meter, 'metrics_ingestion_bytes_ingested_total', {
                description: 'Total uncompressed metric bytes successfully produced for storage, by team',
                unit: 'By',
            }),
            recordsIngested: createCounterWithExemplars(meter, 'metrics_ingestion_records_ingested_total', {
                description: 'Total metric records successfully produced for storage, by team',
            }),
        }
    }
    return instruments
}

function addPositive(counter: Counter, value: number, attributes?: Attributes): void {
    if (value > 0) {
        counter.add(value, attributes)
    }
}

export const recordMetricsIngested = swallowing((teamId: number, bytes: number, records: number): void => {
    const { bytesIngested, recordsIngested } = getInstruments()
    const attributes = { team_id: teamId.toString() }
    addPositive(bytesIngested, bytes, attributes)
    addPositive(recordsIngested, records, attributes)
})

/** Test seam: forget cached instruments so a test-installed provider is picked up. */
export function resetMetricsIngestionInstrumentsForTests(): void {
    instruments = null
}
