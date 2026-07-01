/** Sorts, encodes, and uploads a batch of block-metadata rows as one dt-partitioned Parquet object in the ML bucket. */
import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { randomUUID } from 'crypto'

import { logger } from '~/common/utils/logger'

import { MlBlockMetadataRow } from './block-metadata-row'
import { rowsToParquetBuffer } from './parquet-writer'

const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0)

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
        const body = await rowsToParquetBuffer(rows)
        const key = this.objectKey(minEventDate(rows))
        await this.s3Client.send(
            new PutObjectCommand({
                Bucket: this.bucket,
                Key: key,
                Body: body,
                ContentType: 'application/vnd.apache.parquet',
            })
        )
        logger.info('🪶', 'ml_parquet_metadata_written', { rows: rows.length, bytes: body.length, key })
    }

    /** Partition by event date (`dt=`), but keep a write-time stamp + seq + pod id in the name for uniqueness. */
    private objectKey(dt: string): string {
        this.seq += 1
        return `${this.prefix}/dt=${dt}/part-${this.nodeId}-${Date.now()}-${this.seq}.parquet`
    }
}

/** Partition by the earliest event time in the batch (rows can span a window, so the min wins). */
function minEventDate(rows: MlBlockMetadataRow[]): string {
    let minMs = rows[0].first_ts_ms
    for (const row of rows) {
        if (row.first_ts_ms < minMs) {
            minMs = row.first_ts_ms
        }
    }
    return new Date(minMs).toISOString().slice(0, 10)
}
