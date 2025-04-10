import { Counter } from 'prom-client'

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
}
