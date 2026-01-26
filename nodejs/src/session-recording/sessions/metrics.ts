import { Counter, Histogram } from 'prom-client'

export class SessionBatchMetrics {
    private static readonly batchesFlushed = new Counter({
        name: 'recording_blob_ingestion_v2_batches_flushed_total',
        help: 'Number of session recording batches that have been flushed',
    })

    private static readonly sessionsFlushed = new Counter({
        name: 'recording_blob_ingestion_v2_sessions_flushed_total',
        help: 'Number of individual sessions that have been flushed',
    })

    private static readonly eventsFlushed = new Counter({
        name: 'recording_blob_ingestion_v2_events_flushed_total',
        help: 'Number of individual events that have been flushed',
    })

    private static readonly bytesWritten = new Counter({
        name: 'recording_blob_ingestion_v2_bytes_written_total',
        help: 'Number of bytes written to storage',
    })

    private static readonly consoleLogsStored = new Counter({
        name: 'recording_blob_ingestion_v2_console_logs_stored_total',
        help: 'Number of console logs stored',
    })

    // S3-specific metrics
    private static readonly s3BatchesStarted = new Counter({
        name: 'recording_blob_ingestion_v2_s3_batches_started_total',
        help: 'Number of S3 batch uploads started',
    })

    private static readonly s3BatchesUploaded = new Counter({
        name: 'recording_blob_ingestion_v2_s3_batches_uploaded_total',
        help: 'Number of S3 batch uploads completed successfully',
    })

    private static readonly s3UploadErrors = new Counter({
        name: 'recording_blob_ingestion_v2_s3_upload_errors_total',
        help: 'Number of S3 upload errors',
    })

    private static readonly s3UploadTimeouts = new Counter({
        name: 'recording_blob_ingestion_v2_s3_upload_timeouts_total',
        help: 'Number of S3 upload timeouts',
    })

    private static readonly s3UploadLatency = new Histogram({
        name: 'recording_blob_ingestion_v2_s3_upload_latency_seconds',
        help: 'Time taken to upload batches to S3 in seconds',
        buckets: [0, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300],
    })

    private static readonly s3BytesWritten = new Counter({
        name: 'recording_blob_ingestion_v2_s3_bytes_written_total',
        help: 'Total number of bytes written to S3',
    })

    private static readonly sessionsRateLimited = new Counter({
        name: 'recording_blob_ingestion_v2_sessions_rate_limited_total',
        help: 'Number of sessions that were rate limited',
    })

    private static readonly eventsRateLimited = new Counter({
        name: 'recording_blob_ingestion_v2_events_rate_limited_total',
        help: 'Number of events that were rate limited',
    })

    private static readonly newSessionsDetected = new Counter({
        name: 'recording_blob_ingestion_v2_new_sessions_detected_total',
        help: 'Number of new sessions detected (not seen in Redis within TTL)',
    })

    private static readonly newSessionsRateLimited = new Counter({
        name: 'recording_blob_ingestion_v2_new_sessions_rate_limited_total',
        help: 'Number of new sessions that were rate limited',
    })

    private static readonly sessionTrackerCacheHit = new Counter({
        name: 'recording_blob_ingestion_v2_session_tracker_cache_hit_total',
        help: 'Number of session tracker local cache hits (avoided Redis call)',
    })

    private static readonly sessionTrackerCacheMiss = new Counter({
        name: 'recording_blob_ingestion_v2_session_tracker_cache_miss_total',
        help: 'Number of session tracker local cache misses (required Redis call)',
    })

    private static readonly sessionTrackerRedisErrors = new Counter({
        name: 'recording_blob_ingestion_v2_session_tracker_redis_errors_total',
        help: 'Number of Redis errors in session tracker (failed open)',
    })

    private static readonly sessionsBlocked = new Counter({
        name: 'recording_blob_ingestion_v2_sessions_blocked_total',
        help: 'Number of sessions added to blocklist (will drop all future messages)',
    })

    private static readonly sessionFilterCacheHit = new Counter({
        name: 'recording_blob_ingestion_v2_session_filter_cache_hit_total',
        help: 'Number of session filter local cache hits (avoided Redis call)',
    })

    private static readonly sessionFilterCacheMiss = new Counter({
        name: 'recording_blob_ingestion_v2_session_filter_cache_miss_total',
        help: 'Number of session filter local cache misses (required Redis call)',
    })

    private static readonly sessionFilterRedisErrors = new Counter({
        name: 'recording_blob_ingestion_v2_session_filter_redis_errors_total',
        help: 'Number of Redis errors in session filter (failed open)',
    })

    public static incrementBatchesFlushed(): void {
        this.batchesFlushed.inc()
    }

    public static incrementSessionsFlushed(count: number = 1): void {
        this.sessionsFlushed.inc(count)
    }

    public static incrementEventsFlushed(count: number = 1): void {
        this.eventsFlushed.inc(count)
    }

    public static incrementBytesWritten(bytes: number): void {
        this.bytesWritten.inc(bytes)
    }

    public static incrementConsoleLogsStored(count: number = 1): void {
        this.consoleLogsStored.inc(count)
    }

    // S3-specific metric methods
    public static incrementS3BatchesStarted(): void {
        this.s3BatchesStarted.inc()
    }

    public static incrementS3BatchesUploaded(): void {
        this.s3BatchesUploaded.inc()
    }

    public static incrementS3UploadErrors(): void {
        this.s3UploadErrors.inc()
    }

    public static incrementS3UploadTimeouts(): void {
        this.s3UploadTimeouts.inc()
    }

    public static observeS3UploadLatency(seconds: number): void {
        this.s3UploadLatency.observe(seconds)
    }

    public static incrementS3BytesWritten(bytes: number): void {
        this.s3BytesWritten.inc(bytes)
    }

    public static incrementSessionsRateLimited(count: number = 1): void {
        this.sessionsRateLimited.inc(count)
    }

    public static incrementEventsRateLimited(count: number = 1): void {
        this.eventsRateLimited.inc(count)
    }

    public static incrementNewSessionsDetected(count: number = 1): void {
        this.newSessionsDetected.inc(count)
    }

    public static incrementNewSessionsRateLimited(count: number = 1): void {
        this.newSessionsRateLimited.inc(count)
    }

    public static incrementSessionTrackerCacheHit(count: number = 1): void {
        this.sessionTrackerCacheHit.inc(count)
    }

    public static incrementSessionTrackerCacheMiss(count: number = 1): void {
        this.sessionTrackerCacheMiss.inc(count)
    }

    public static incrementSessionTrackerRedisErrors(count: number = 1): void {
        this.sessionTrackerRedisErrors.inc(count)
    }

    public static incrementSessionsBlocked(count: number = 1): void {
        this.sessionsBlocked.inc(count)
    }

    public static incrementSessionFilterCacheHit(count: number = 1): void {
        this.sessionFilterCacheHit.inc(count)
    }

    public static incrementSessionFilterCacheMiss(count: number = 1): void {
        this.sessionFilterCacheMiss.inc(count)
    }

    public static incrementSessionFilterRedisErrors(count: number = 1): void {
        this.sessionFilterRedisErrors.inc(count)
    }
}
