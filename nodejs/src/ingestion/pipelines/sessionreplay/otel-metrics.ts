import { Attributes, Counter, Histogram, metrics as metricsApi } from '@opentelemetry/api'

import { createCounterWithExemplars, createHistogramWithExemplars, swallowing } from '~/common/metrics/instruments'

/**
 * OTLP-pushed twins of the core session replay ingestion prom counters. The prom side keeps
 * feeding the scrape/VictoriaMetrics dashboards; these land in the PostHog metrics product
 * through the exporter installed by initMetrics (common/metrics/otel-metrics.ts).
 *
 * Names and label sets deliberately match the prom counters so dashboards translate 1:1.
 *
 * Instruments are acquired lazily on first record: the OTel metrics API has no proxy
 * provider, so instruments created at module load (before initMetrics runs) would be
 * bound to the noop meter forever.
 */

interface ReplayIngestionInstruments {
    sessionsFlushed: Counter
    eventsFlushed: Counter
    bytesWritten: Counter
    sessionsDroppedMissingRetention: Counter
    messagesDroppedByRestrictions: Counter
    sessionsRateLimited: Counter
    eventsRateLimited: Counter
    sessionsBlocked: Counter
    newSessionsRateLimited: Counter
    s3UploadErrors: Counter
    s3UploadTimeouts: Counter
    s3UploadLatency: Histogram
    e2eLag: Histogram
}

/** Keep in lockstep with the recording_blob_ingestion_v2_s3_upload_latency_seconds prom buckets. */
const S3_UPLOAD_LATENCY_BOUNDARIES = [0, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300]

/** Buffering dominates the lag, so buckets span seconds to the batch-flush ceiling and beyond. */
export const E2E_LAG_BOUNDARIES = [5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600]

let instruments: ReplayIngestionInstruments | null = null

function getInstruments(): ReplayIngestionInstruments {
    if (instruments === null) {
        const meter = metricsApi.getMeter('session-replay-ingestion')
        instruments = {
            sessionsFlushed: createCounterWithExemplars(meter, 'recording_blob_ingestion_v2_sessions_flushed_total', {
                description: 'Number of individual sessions that have been flushed',
            }),
            eventsFlushed: createCounterWithExemplars(meter, 'recording_blob_ingestion_v2_events_flushed_total', {
                description: 'Number of individual events that have been flushed',
            }),
            bytesWritten: createCounterWithExemplars(meter, 'recording_blob_ingestion_v2_bytes_written_total', {
                description: 'Number of bytes written to storage',
                unit: 'By',
            }),
            sessionsDroppedMissingRetention: createCounterWithExemplars(
                meter,
                'recording_blob_ingestion_v2_sessions_dropped_missing_retention_total',
                {
                    description: 'Number of sessions dropped before recording because retention could not be resolved',
                }
            ),
            messagesDroppedByRestrictions: createCounterWithExemplars(
                meter,
                'recording_blob_ingestion_v2_messages_dropped_by_restrictions',
                { description: 'The number of messages dropped due to event ingestion restrictions' }
            ),
            sessionsRateLimited: createCounterWithExemplars(
                meter,
                'recording_blob_ingestion_v2_sessions_rate_limited_total',
                {
                    description: 'Number of sessions that were rate limited',
                }
            ),
            eventsRateLimited: createCounterWithExemplars(
                meter,
                'recording_blob_ingestion_v2_events_rate_limited_total',
                {
                    description: 'Number of events that were rate limited',
                }
            ),
            sessionsBlocked: createCounterWithExemplars(meter, 'recording_blob_ingestion_v2_sessions_blocked_total', {
                description: 'Number of sessions dropped by the session filter blocklist',
            }),
            newSessionsRateLimited: createCounterWithExemplars(
                meter,
                'recording_blob_ingestion_v2_new_sessions_rate_limited_total',
                { description: 'Number of new sessions dropped by the per-team new-session rate limiter' }
            ),
            s3UploadErrors: createCounterWithExemplars(meter, 'recording_blob_ingestion_v2_s3_upload_errors_total', {
                description: 'Number of S3 upload errors',
            }),
            s3UploadTimeouts: createCounterWithExemplars(
                meter,
                'recording_blob_ingestion_v2_s3_upload_timeouts_total',
                {
                    description: 'Number of S3 upload timeouts',
                }
            ),
            s3UploadLatency: createHistogramWithExemplars(
                meter,
                'recording_blob_ingestion_v2_s3_upload_latency_seconds',
                {
                    description: 'Time taken to upload batches to S3 in seconds',
                    unit: 's',
                    advice: { explicitBucketBoundaries: S3_UPLOAD_LATENCY_BOUNDARIES },
                }
            ),
            e2eLag: createHistogramWithExemplars(meter, 'recording_blob_ingestion_v2_e2e_lag_seconds', {
                description: 'Per-session staleness at flush: wall clock minus the newest flushed event timestamp',
                unit: 's',
                advice: { explicitBucketBoundaries: E2E_LAG_BOUNDARIES },
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

export const recordSessionsFlushed = swallowing((count: number): void => {
    addPositive(getInstruments().sessionsFlushed, count)
})

export const recordEventsFlushed = swallowing((count: number): void => {
    addPositive(getInstruments().eventsFlushed, count)
})

export const recordBytesWritten = swallowing((bytes: number): void => {
    addPositive(getInstruments().bytesWritten, bytes)
})

export const recordSessionsDroppedMissingRetention = swallowing((count: number): void => {
    addPositive(getInstruments().sessionsDroppedMissingRetention, count)
})

export const recordMessagesDroppedByRestrictions = swallowing((count: number): void => {
    addPositive(getInstruments().messagesDroppedByRestrictions, count)
})

export const recordSessionsRateLimited = swallowing((count: number): void => {
    addPositive(getInstruments().sessionsRateLimited, count)
})

export const recordEventsRateLimited = swallowing((count: number): void => {
    addPositive(getInstruments().eventsRateLimited, count)
})

export const recordSessionsBlocked = swallowing((count: number): void => {
    addPositive(getInstruments().sessionsBlocked, count)
})

export const recordNewSessionsRateLimited = swallowing((teamId: number, count: number): void => {
    addPositive(getInstruments().newSessionsRateLimited, count, { team_id: teamId.toString() })
})

export const recordS3UploadError = swallowing((): void => {
    getInstruments().s3UploadErrors.add(1)
})

export const recordS3UploadTimeout = swallowing((): void => {
    getInstruments().s3UploadTimeouts.add(1)
})

export const recordS3UploadLatency = swallowing((seconds: number): void => {
    getInstruments().s3UploadLatency.record(seconds)
})

export const recordE2eLag = swallowing((seconds: number): void => {
    getInstruments().e2eLag.record(seconds)
})

/** Test seam: forget cached instruments so a test-installed provider is picked up. */
export function resetReplayIngestionInstrumentsForTests(): void {
    instruments = null
}
