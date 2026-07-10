import { Attributes, Counter, Histogram, metrics as metricsApi } from '@opentelemetry/api'

/**
 * OTLP-pushed twins of the core logs-ingestion prom counters. The prom side keeps
 * feeding the scrape/VictoriaMetrics dashboards; these land in the PostHog metrics
 * product through the exporter installed by initMetrics (common/metrics/otel-metrics.ts),
 * with per-replica resource identity instead of the bridge's collapsed scrape identity.
 *
 * Names and label sets deliberately match the prom counters so dashboards translate 1:1.
 *
 * Instruments are acquired lazily on first record: the OTel metrics API has no proxy
 * provider, so instruments created at module load (before initMetrics runs) would be
 * bound to the noop meter forever.
 */

interface LogsIngestionInstruments {
    bytesReceived: Counter
    recordsReceived: Counter
    bytesAllowed: Counter
    recordsAllowed: Counter
    bytesDropped: Counter
    recordsDropped: Counter
    messagesDropped: Counter
    messagesDlq: Counter
    processingDuration: Histogram
}

/** Keep in lockstep with the logs_ingestion_processing_duration_seconds prom buckets. */
const PROCESSING_DURATION_BOUNDARIES = [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1]

let instruments: LogsIngestionInstruments | null = null

function getInstruments(): LogsIngestionInstruments {
    if (instruments === null) {
        const meter = metricsApi.getMeter('logs-ingestion')
        instruments = {
            bytesReceived: meter.createCounter('logs_ingestion_bytes_received_total', {
                description: 'Total uncompressed bytes received for logs ingestion',
                unit: 'By',
            }),
            recordsReceived: meter.createCounter('logs_ingestion_records_received_total', {
                description: 'Total log records received',
            }),
            bytesAllowed: meter.createCounter('logs_ingestion_bytes_allowed_total', {
                description: 'Total uncompressed bytes allowed through quota and rate limiting',
                unit: 'By',
            }),
            recordsAllowed: meter.createCounter('logs_ingestion_records_allowed_total', {
                description: 'Total log records allowed through quota and rate limiting',
            }),
            bytesDropped: meter.createCounter('logs_ingestion_bytes_dropped_total', {
                description: 'Total uncompressed bytes dropped due to quota or rate limiting',
                unit: 'By',
            }),
            recordsDropped: meter.createCounter('logs_ingestion_records_dropped_total', {
                description: 'Total log records dropped due to quota or rate limiting',
            }),
            messagesDropped: meter.createCounter('logs_ingestion_message_dropped_count', {
                description: 'The number of logs ingestion messages dropped',
            }),
            messagesDlq: meter.createCounter('logs_ingestion_message_dlq_count', {
                description: 'The number of logs ingestion messages sent to DLQ',
            }),
            processingDuration: meter.createHistogram('logs_ingestion_processing_duration_seconds', {
                description: 'Time spent processing log messages (AVRO decode/encode cycle)',
                unit: 's',
                advice: { explicitBucketBoundaries: PROCESSING_DURATION_BOUNDARIES },
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

/**
 * These run in finally blocks and error handlers of the ingestion hot path — a throw
 * here would mask the real processing error and DLQ the message with the wrong reason,
 * so recording failures are swallowed.
 */
function swallowing<Args extends unknown[]>(record: (...args: Args) => void): (...args: Args) => void {
    return (...args: Args): void => {
        try {
            record(...args)
        } catch {
            // never let telemetry break ingestion
        }
    }
}

export const recordLogsReceived = swallowing((bytes: number, records: number): void => {
    const { bytesReceived, recordsReceived } = getInstruments()
    addPositive(bytesReceived, bytes)
    addPositive(recordsReceived, records)
})

export const recordLogsAllowed = swallowing((bytes: number, records: number): void => {
    const { bytesAllowed, recordsAllowed } = getInstruments()
    addPositive(bytesAllowed, bytes)
    addPositive(recordsAllowed, records)
})

export const recordLogsDropped = swallowing((teamId: number, bytes: number, records: number): void => {
    const { bytesDropped, recordsDropped } = getInstruments()
    const attributes = { team_id: teamId.toString() }
    addPositive(bytesDropped, bytes, attributes)
    addPositive(recordsDropped, records, attributes)
})

export const recordLogMessageDropped = swallowing((reason: string, teamId: string, count: number = 1): void => {
    addPositive(getInstruments().messagesDropped, count, { reason, team_id: teamId })
})

export const recordLogMessageDlq = swallowing((reason: string, teamId: string): void => {
    getInstruments().messagesDlq.add(1, { reason, team_id: teamId })
})

export const recordLogProcessingDuration = swallowing(
    (
        seconds: number,
        attributes: { json_parse_enabled: string; pii_scrub_enabled: string; compression_codec: string }
    ): void => {
        getInstruments().processingDuration.record(seconds, attributes)
    }
)

/** Test seam: forget cached instruments so a test-installed provider is picked up. */
export function resetLogsIngestionInstrumentsForTests(): void {
    instruments = null
}
