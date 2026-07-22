/** Sorts, encodes, and uploads a batch of block-metadata rows as one dt-partitioned Parquet object in the ML bucket. */
import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { randomUUID } from 'crypto'

import { logger } from '~/common/utils/logger'

import { MlBlockMetadataRow } from './block-metadata-row'
import { MlParquetSinkMetrics } from './metrics'
import { rowsToParquetBuffer } from './parquet-writer'

const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0)

const DAY_MS = 86_400_000
// The `dt=` partition is a UTC date, so measure lag and span in whole UTC days to match it.
const utcDay = (ms: number): number => Math.floor(ms / DAY_MS)

export class BlockMetadataParquetStore {
    private seq = 0
    private readonly nodeId: string

    constructor(
        private readonly s3Client: S3Client,
        private readonly bucket: string,
        private readonly prefix: string,
        nodeId?: string
    ) {
        // Stable per-pod id so concurrent writers can't collide on a key.
        this.nodeId = nodeId || process.env.HOSTNAME || randomUUID().slice(0, 8)
    }

    /** Writes the rows as one Parquet object. Throws on failure so the caller can replay from Kafka (at-least-once). */
    public async write(rows: MlBlockMetadataRow[]): Promise<void> {
        if (rows.length === 0) {
            return
        }
        // Sorting clusters a recording's blocks together for better compression and reads.
        rows.sort((a, b) => cmp(a.team_id, b.team_id) || cmp(a.session_id, b.session_id))
        let body: Buffer
        let key: string
        let bounds: { minMs: number; maxMs: number }
        try {
            // Encoding, key derivation, and upload all count as write failures: each leaves the batch to
            // replay from Kafka, so the counter must see them, not just the S3 send.
            body = await rowsToParquetBuffer(rows)
            bounds = eventTimeBounds(rows)
            key = this.objectKey(new Date(bounds.minMs).toISOString().slice(0, 10))
            await this.s3Client.send(
                new PutObjectCommand({
                    Bucket: this.bucket,
                    Key: key,
                    Body: body,
                    ContentType: 'application/vnd.apache.parquet',
                })
            )
        } catch (error) {
            MlParquetSinkMetrics.incWriteError()
            throw error
        }
        MlParquetSinkMetrics.observeWrite(rows.length, body.length)
        // The object's partition date is its oldest event day, so a mixed-date batch (span > 0) lands most
        // of its rows under an understated dt. Expose both so a stale partition from a straggler is visible.
        MlParquetSinkMetrics.observePartition(
            utcDay(Date.now()) - utcDay(bounds.minMs),
            utcDay(bounds.maxMs) - utcDay(bounds.minMs)
        )
        logger.info('🪶', 'ml_parquet_metadata_written', { rows: rows.length, bytes: body.length, key })
    }

    /** Partition by event date (`dt=`), but keep a write-time stamp + seq + pod id in the name for uniqueness. */
    private objectKey(dt: string): string {
        this.seq += 1
        return `${this.prefix}/dt=${dt}/part-${this.nodeId}-${Date.now()}-${this.seq}.parquet`
    }
}

/**
 * Earliest and latest event time in the batch. The earliest sets the object's `dt=` partition (rows can
 * span a window, so the min wins); the latest lets the caller measure how far the batch's dates spread.
 */
function eventTimeBounds(rows: MlBlockMetadataRow[]): { minMs: number; maxMs: number } {
    let minMs = rows[0].first_ts_ms
    let maxMs = rows[0].first_ts_ms
    for (const row of rows) {
        if (row.first_ts_ms < minMs) {
            minMs = row.first_ts_ms
        }
        if (row.first_ts_ms > maxMs) {
            maxMs = row.first_ts_ms
        }
    }
    return { minMs, maxMs }
}
