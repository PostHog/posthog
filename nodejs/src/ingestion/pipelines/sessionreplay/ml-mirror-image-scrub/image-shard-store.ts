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

const INDEX_FORMAT_VERSION = 1

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
        this.nodeId = nodeId || process.env.HOSTNAME || randomUUID().slice(0, 8)
    }

    // S3 client has no request timeout; a hung write would stall the poll loop past Kafka's max.poll.interval.ms and evict us.
    private async send(command: PutObjectCommand): Promise<void> {
        const controller = new AbortController()
        const timer = setTimeout(() => controller.abort(), this.writeTimeoutMs)
        try {
            await this.s3.send(command, { abortSignal: controller.signal })
        } finally {
            clearTimeout(timer)
        }
    }

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

        // Shard before index: an index pointing at a missing shard breaks reads; a dangling shard only wastes storage.
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
