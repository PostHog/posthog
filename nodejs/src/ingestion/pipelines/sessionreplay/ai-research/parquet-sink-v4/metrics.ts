import { Counter } from 'prom-client'

import { V4Index } from './index-columns'

export type V4RowRejection = 'parse_failed' | 'invalid_row' | 'unknown_index' | 'invalid_write_day'

export class V4ParquetSinkMetrics {
    private static readonly rowsParsed = new Counter({
        name: 'ai_research_v4_parquet_sink_rows_parsed_total',
        help: 'v4 index rows read from Kafka and accepted into the Parquet buffer',
        labelNames: ['index'],
    })
    private static readonly rowsRejected = new Counter({
        name: 'ai_research_v4_parquet_sink_rows_rejected_total',
        help: 'v4 index messages skipped before buffering, by reason',
        labelNames: ['reason'],
    })
    private static readonly invalidColumns = new Counter({
        name: 'ai_research_v4_parquet_sink_invalid_columns_total',
        help: 'v4 index rows rejected as invalid_row, by index and the first column that was missing or did not fit its type',
        labelNames: ['index', 'column'],
    })
    private static readonly rowsReleased = new Counter({
        name: 'ai_research_v4_parquet_sink_rows_released_total',
        help: 'Buffered v4 index rows left out of the next file because their partition was revoked; the new owner reads them again',
    })
    private static readonly filesWritten = new Counter({
        name: 'ai_research_v4_parquet_sink_files_written_total',
        help: 'v4 index Parquet files written',
        labelNames: ['index'],
    })
    private static readonly rowsWritten = new Counter({
        name: 'ai_research_v4_parquet_sink_rows_written_total',
        help: 'v4 index rows written as Parquet, including rows written again after a replay',
        labelNames: ['index'],
    })
    private static readonly bytesWritten = new Counter({
        name: 'ai_research_v4_parquet_sink_bytes_written_total',
        help: 'v4 index Parquet bytes written',
        labelNames: ['index'],
    })
    private static readonly writeErrors = new Counter({
        name: 'ai_research_v4_parquet_sink_write_errors_total',
        help: 'v4 index file writes that threw; the rows stay buffered and their offsets stay uncommitted',
    })
    private static readonly flushes = new Counter({
        name: 'ai_research_v4_parquet_sink_flushes_total',
        help: 'v4 sink flushes by outcome: wrote files, or committed offsets of messages that gave no rows',
        labelNames: ['outcome'],
    })

    public static incRowsParsed(index: V4Index): void {
        this.rowsParsed.labels(index).inc()
    }
    public static incRowsRejected(reason: V4RowRejection): void {
        this.rowsRejected.labels(reason).inc()
    }
    public static incInvalidColumn(index: V4Index, column: string): void {
        this.invalidColumns.labels(index, column).inc()
    }
    public static incRowsReleased(count: number): void {
        this.rowsReleased.inc(count)
    }
    public static observeFile(index: V4Index, rows: number, bytes: number): void {
        this.filesWritten.labels(index).inc()
        this.rowsWritten.labels(index).inc(rows)
        this.bytesWritten.labels(index).inc(bytes)
    }
    public static incWriteError(): void {
        this.writeErrors.inc()
    }
    public static incFlush(outcome: 'written' | 'empty'): void {
        this.flushes.labels(outcome).inc()
    }
}
