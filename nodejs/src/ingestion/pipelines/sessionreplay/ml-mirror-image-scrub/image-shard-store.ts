/**
 * Scrubbed images written as one shard blob + one parquet index per FLUSH (a flush spans many teams): one
 * S3 object per image would explode request costs (a page can inline hundreds), so we concatenate. Read
 * `image:{pseudo_team}:{hash}` by scanning the index for (pseudo_team, hash) then range-GET the shard.
 *
 *   {prefix}/shards/{node}-{ts}-{seq}.bin       raw concat of scrubbed image bytes (many teams)
 *   {prefix}/index/{node}-{ts}-{seq}.parquet    rows: format_version, pseudo_team, hash, shard, offset, length
 *
 * The team segment is a non-reversible HMAC pseudonym (ml-mirror/pseudonymize.ts), so no raw team id reaches
 * the ML bucket, matching the block-metadata dataset.
 */
import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { ParquetSchema } from '@dsnp/parquetjs'
import { randomUUID } from 'node:crypto'

import { parquetRecordsToBuffer } from '~/ingestion/pipelines/sessionreplay/shared/parquet'

export interface ScrubbedImage {
    pseudoTeam: string
    hash: string
    bytes: Buffer
}

interface IndexRow {
    pseudoTeam: string
    hash: string
    shard: string
    offset: number
    length: number
}

// Stamped on every index row so a future format change (Stage 2 columns, layout) is detectable and a reader
// built against v1 can fail closed on an unknown version instead of silently misparsing.
const INDEX_FORMAT_VERSION = 1

// Snappy per column (compression is a per-field option in parquetjs, not a writer option).
const INDEX_SCHEMA = new ParquetSchema({
    format_version: { type: 'INT64', compression: 'SNAPPY' },
    pseudo_team: { type: 'UTF8', compression: 'SNAPPY' },
    hash: { type: 'UTF8', compression: 'SNAPPY' },
    shard: { type: 'UTF8', compression: 'SNAPPY' },
    offset: { type: 'INT64', compression: 'SNAPPY' },
    length: { type: 'INT64', compression: 'SNAPPY' },
})

function indexRowsToParquet(rows: IndexRow[]): Promise<Buffer> {
    return parquetRecordsToBuffer(
        INDEX_SCHEMA,
        rows.map((r) => ({
            format_version: BigInt(INDEX_FORMAT_VERSION),
            pseudo_team: r.pseudoTeam,
            hash: r.hash,
            shard: r.shard,
            offset: BigInt(r.offset),
            length: BigInt(r.length),
        }))
    )
}

export class ImageShardStore {
    private seq = 0
    private readonly nodeId: string

    constructor(
        private readonly s3: S3Client,
        private readonly bucket: string,
        private readonly prefix: string,
        private readonly writeTimeoutMs: number,
        nodeId?: string
    ) {
        // Stable per-pod id so concurrent writers can't collide on a key.
        this.nodeId = nodeId || process.env.HOSTNAME || randomUUID().slice(0, 8)
    }

    /** PutObject with a wall-clock timeout. The S3 client has no request timeout, so a hung write would
     *  otherwise stall the poll loop past max.poll.interval.ms and get the consumer evicted; on timeout the
     *  send aborts and writeShard throws, leaving the window to replay. */
    private async send(command: PutObjectCommand): Promise<void> {
        const controller = new AbortController()
        const timer = setTimeout(() => controller.abort(), this.writeTimeoutMs)
        try {
            await this.s3.send(command, { abortSignal: controller.signal })
        } finally {
            clearTimeout(timer)
        }
    }

    /** A whole flush's images (many teams) as one shard blob + one parquet index carrying pseudo_team per row.
     *  Throws on failure so the caller replays from Kafka; redelivery writes a fresh shard (reader dedups by
     *  (pseudo_team, hash)), and a mid-write orphaned shard is invisible since no index points at it. */
    public async writeShard(images: ScrubbedImage[]): Promise<{ shard: string; bytes: number }> {
        this.seq += 1
        const stamp = `${this.nodeId}-${Date.now()}-${this.seq}`
        const shardKey = `${this.prefix}/shards/${stamp}.bin`

        const rows: IndexRow[] = []
        const parts: Buffer[] = []
        let offset = 0
        for (const img of images) {
            rows.push({ pseudoTeam: img.pseudoTeam, hash: img.hash, shard: shardKey, offset, length: img.bytes.length })
            parts.push(img.bytes)
            offset += img.bytes.length
        }
        const shardBody = Buffer.concat(parts, offset)
        const indexBody = await indexRowsToParquet(rows)

        // Shard first, then index: a dangling shard (index write failed) just wastes storage, whereas an
        // index pointing at a missing shard would break reads.
        await this.send(
            new PutObjectCommand({
                Bucket: this.bucket,
                Key: shardKey,
                Body: shardBody,
                ContentType: 'application/octet-stream',
            })
        )
        await this.send(
            new PutObjectCommand({
                Bucket: this.bucket,
                Key: `${this.prefix}/index/${stamp}.parquet`,
                Body: indexBody,
                ContentType: 'application/vnd.apache.parquet',
            })
        )
        return { shard: shardKey, bytes: offset }
    }
}
