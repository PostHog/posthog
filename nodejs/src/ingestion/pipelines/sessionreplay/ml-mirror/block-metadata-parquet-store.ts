/** Sorts, encodes, and uploads a batch of block-metadata rows as one dt-partitioned Parquet object in the ML bucket. */
import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { ParquetSchema } from '@dsnp/parquetjs'
import { randomUUID } from 'crypto'

import { logger } from '~/common/utils/logger'
import { parquetRecordsToBuffer } from '~/ingestion/pipelines/sessionreplay/shared/parquet'

import { MlBlockMetadataRow } from './block-metadata-row'
import { MlEncryptedEnvelope } from './keys/crypto'
import { MlParquetSinkMetrics } from './metrics'
import { rowsToParquetBuffer } from './parquet-writer'
import {
    EncryptedReplayIndex,
    replayIndexPartitions,
    replayIndexToParquetBuffer,
    v3ReplayIndexByKind,
} from './replay-index'
import { sessionStartMonth, usesV3Dataset } from './session-identifier-format'

const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0)

const DAY_MS = 86_400_000
// The `dt=` partition is a UTC date, so measure lag and span in whole UTC days to match it.
const utcDay = (ms: number): number => Math.floor(ms / DAY_MS)

/** A session's start selects its dataset, and each dataset has a bucket of its own. */
export interface MlDatasetBuckets {
    v2: string
    v3: string
}

export class BlockMetadataParquetStore {
    private seq = 0
    private readonly nodeId: string

    constructor(
        private readonly s3Client: S3Client,
        private readonly buckets: MlDatasetBuckets,
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
        if (rows.some((row) => row.format_version === 2)) {
            throw new Error('ML raw-identifier metadata must use sealed v2 or plain v3 storage')
        }
        await this.writeDataset(rows, this.prefix, `${this.prefix}-replay-index/v1`)
    }

    public async writeEncrypted(envelopes: MlEncryptedEnvelope[]): Promise<void> {
        if (envelopes.length === 0) {
            return
        }
        const partitions = new Map<string, MlEncryptedEnvelope[]>()
        for (const envelope of envelopes) {
            const partition = `${this.prefix}/v2/${sealedSessionMonth(envelope)}`
            const group = partitions.get(partition) ?? []
            group.push(envelope)
            partitions.set(partition, group)
        }
        for (const [partition, group] of partitions) {
            const bytes = await this.writeEncryptedPartition(partition, group)
            MlParquetSinkMetrics.observeWrite(group.length, bytes)
        }
    }

    public async writeEncryptedReplayIndex(indexes: EncryptedReplayIndex[]): Promise<void> {
        const partitions = new Map<string, EncryptedReplayIndex[]>()
        for (const index of indexes) {
            const partition = `${this.prefix}-replay-index/v2/${sealedSessionMonth(index.envelope)}/kind=${index.kind}`
            const group = partitions.get(partition) ?? []
            group.push(index)
            partitions.set(partition, group)
        }
        for (const [partition, group] of partitions) {
            await this.writeEncryptedPartition(
                partition,
                group.map((index) => index.envelope)
            )
            MlParquetSinkMetrics.incReplayIndexRows(
                group[0].kind,
                group.reduce((count, index) => count + index.rowCount, 0)
            )
        }
    }

    /** Writes v3 metadata and its replay index as plain Parquet columns, partitioned by the session's UTC start month. */
    public async writePlainV3(rows: MlBlockMetadataRow[]): Promise<void> {
        const months = new Map<string, MlBlockMetadataRow[]>()
        for (const row of rows) {
            if (!usesV3Dataset(row.session_id)) {
                throw new Error('ML plain storage holds only v3 sessions')
            }
            const month = sessionStartMonth(row.session_id)
            const group = months.get(month) ?? []
            group.push(row)
            months.set(month, group)
        }
        try {
            // Every body is encoded before the first upload, so a row that the writer rejects leaves no object behind.
            const uploads: { prefix: string; body: Buffer; rows: number; indexKind?: string }[] = []
            for (const [month, group] of months) {
                group.sort((a, b) => cmp(a.team_id, b.team_id) || cmp(a.session_id, b.session_id))
                for (const [kind, records] of v3ReplayIndexByKind(group)) {
                    uploads.push({
                        prefix: `${this.prefix}-replay-index/v3/${month}/kind=${kind}`,
                        body: await replayIndexToParquetBuffer(records),
                        rows: records.length,
                        indexKind: kind,
                    })
                }
                uploads.push({
                    prefix: `${this.prefix}/v3/${month}`,
                    body: await rowsToParquetBuffer(group),
                    rows: group.length,
                })
            }
            for (const upload of uploads) {
                await this.putParquet(this.buckets.v3, upload.prefix, upload.body)
                if (upload.indexKind) {
                    MlParquetSinkMetrics.incReplayIndexRows(upload.indexKind, upload.rows)
                } else {
                    MlParquetSinkMetrics.observeWrite(upload.rows, upload.body.length)
                }
            }
        } catch (error) {
            MlParquetSinkMetrics.incWriteError()
            throw error
        }
    }

    private async writeEncryptedPartition(prefix: string, envelopes: MlEncryptedEnvelope[]): Promise<number> {
        let body: Buffer
        try {
            const schema = new ParquetSchema({
                format_version: { type: 'INT64' },
                team_id: { type: 'UTF8' },
                session_id: { type: 'UTF8' },
                payload: { type: 'BYTE_ARRAY' },
            })
            body = await parquetRecordsToBuffer(
                schema,
                envelopes.map((envelope) => ({
                    format_version: 2n,
                    team_id: String(envelope.context.teamId),
                    session_id: envelope.context.sessionId,
                    payload: Buffer.from(JSON.stringify(envelope)),
                }))
            )
            await this.putParquet(this.buckets.v2, prefix, body)
        } catch (error) {
            MlParquetSinkMetrics.incWriteError()
            throw error
        }
        return body.length
    }

    private async putParquet(bucket: string, prefix: string, body: Buffer): Promise<void> {
        await this.s3Client.send(
            new PutObjectCommand({
                Bucket: bucket,
                Key: `${prefix}/part-${this.nodeId}-${Date.now()}-${++this.seq}.parquet`,
                Body: body,
                ContentType: 'application/vnd.apache.parquet',
            }),
            { abortSignal: AbortSignal.timeout(30_000) }
        )
    }

    private async writeDataset(rows: MlBlockMetadataRow[], prefix: string, indexPrefix: string): Promise<void> {
        // Sorting clusters a recording's blocks together for better compression and reads.
        rows.sort((a, b) => cmp(a.team_id, b.team_id) || cmp(a.session_id, b.session_id))
        let body: Buffer
        let key: string
        let bounds: { minMs: number; maxMs: number }
        try {
            // Encoding, key derivation, and upload all count as write failures: each leaves the batch to
            // replay from Kafka, so the counter must see them, not just the S3 send.
            for (const [partition, records] of replayIndexPartitions(rows)) {
                const indexBody = await replayIndexToParquetBuffer(records)
                this.seq += 1
                await this.s3Client.send(
                    new PutObjectCommand({
                        Bucket: this.buckets.v2,
                        Key: `${indexPrefix}/${partition}/part-${this.nodeId}-${Date.now()}-${this.seq}.parquet`,
                        Body: indexBody,
                        ContentType: 'application/vnd.apache.parquet',
                    })
                )
                MlParquetSinkMetrics.incReplayIndexRows(String(records[0].kind), records.length)
            }
            body = await rowsToParquetBuffer(rows)
            bounds = eventTimeBounds(rows)
            key = this.objectKey(prefix, new Date(bounds.minMs).toISOString().slice(0, 10))
            await this.s3Client.send(
                new PutObjectCommand({
                    Bucket: this.buckets.v2,
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
    private objectKey(prefix: string, dt: string): string {
        this.seq += 1
        return `${prefix}/dt=${dt}/part-${this.nodeId}-${Date.now()}-${this.seq}.parquet`
    }
}

function sealedSessionMonth(envelope: MlEncryptedEnvelope): string {
    const sessionId = envelope.context.sessionId ?? ''
    if (usesV3Dataset(sessionId)) {
        throw new Error('ML v3 metadata uses plain storage')
    }
    return sessionStartMonth(sessionId)
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
