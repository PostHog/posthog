import { Counter } from 'prom-client'

/**
 * Metrics for the ML block-metadata Parquet sink (drains the mirror's block-metadata topic to the ML
 * bucket). The sink can consume and commit offsets while writing nothing: if every row is rejected the
 * buffer stays empty, so flush advances offsets without a write. Kafka lag alone can't see that state.
 */
export class MlParquetSinkMetrics {
    private static readonly rowsParsed = new Counter({
        name: 'ml_mirror_parquet_sink_rows_parsed_total',
        help: 'Block-metadata rows parsed from Kafka and accepted into the Parquet buffer',
    })
    private static readonly rowsRejected = new Counter({
        name: 'ml_mirror_parquet_sink_rows_rejected_total',
        help: 'Block-metadata Kafka messages skipped before buffering, by reason',
        labelNames: ['reason'],
    })
    private static readonly objectsWritten = new Counter({
        name: 'ml_mirror_parquet_sink_objects_written_total',
        help: 'Parquet objects written to the ML bucket',
    })
    private static readonly rowsWritten = new Counter({
        name: 'ml_mirror_parquet_sink_rows_written_total',
        help: 'Block-metadata rows written to the ML bucket as Parquet',
    })
    private static readonly bytesWritten = new Counter({
        name: 'ml_mirror_parquet_sink_bytes_written_total',
        help: 'Parquet bytes written to the ML bucket',
    })
    private static readonly writeErrors = new Counter({
        name: 'ml_mirror_parquet_sink_write_errors_total',
        help: 'Parquet object writes that threw (the batch replays from Kafka)',
    })
    private static readonly flushes = new Counter({
        name: 'ml_mirror_parquet_sink_flushes_total',
        help: 'Batcher flushes by outcome: wrote a Parquet object, or committed offsets with an empty buffer',
        labelNames: ['outcome'],
    })

    public static incRowsParsed(count: number): void {
        this.rowsParsed.inc(count)
    }
    public static incRowsRejected(reason: 'parse_failed' | 'invalid'): void {
        this.rowsRejected.labels(reason).inc()
    }
    public static observeWrite(rows: number, bytes: number): void {
        this.objectsWritten.inc()
        this.rowsWritten.inc(rows)
        this.bytesWritten.inc(bytes)
    }
    public static incWriteError(): void {
        this.writeErrors.inc()
    }
    public static incFlush(outcome: 'written' | 'empty'): void {
        this.flushes.labels(outcome).inc()
    }
}
