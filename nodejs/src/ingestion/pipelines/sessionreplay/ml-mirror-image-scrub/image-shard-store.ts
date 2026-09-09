import { DeleteObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { ParquetSchema } from '@dsnp/parquetjs'
import { randomUUID } from 'node:crypto'

import { logger } from '~/common/utils/logger'
import { parquetRecordsToBuffer } from '~/ingestion/pipelines/sessionreplay/shared/parquet'

export interface ScrubbedImage {
    pseudoTeam: string
    hash: string
    bytes: Buffer
}

export interface ScrubbedUrlImage {
    hash: string
    bytes: Buffer
    sourcePartition: number
    sourceOffset: number
}

export type UrlImageWriteOutcome = 'created' | 'already_exists'

interface IndexRow {
    pseudoTeam: string
    hash: string
    shard: string
    offset: number
    length: number
}

const INDEX_FORMAT_VERSION = 1
const URL_SOURCE_PARTITION_METADATA = 'source-partition'
const URL_SOURCE_OFFSET_METADATA = 'source-offset'
const URL_WRITE_MAX_ATTEMPTS = 8
const S3_WRITE_MAX_ATTEMPTS = 3
/**
 * A ceiling on the time one object may spend in retries.
 *
 * Each attempt is already capped by writeTimeoutMs, so repeated timeouts across both objects of a
 * shard write would otherwise approach the 300 second max.poll.interval.ms that governs the whole
 * batch. The budget ends the retries before a slow flush can cost the pod its partitions.
 */
const S3_WRITE_RETRY_BUDGET_MS = 45_000
const S3_WRITE_RETRY_BASE_MS = 100
const S3_WRITE_RETRY_MAX_BACKOFF_MS = 2_000

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
        nodeId?: string,
        // unref'd, so a backoff that is still pending cannot hold the event loop open through shutdown.
        private readonly sleep: (ms: number) => Promise<void> = (ms) =>
            new Promise((resolve) => setTimeout(resolve, ms).unref())
    ) {
        this.nodeId = nodeId || process.env.HOSTNAME || randomUUID().slice(0, 8)
    }

    /**
     * One S3 request, bounded by a timeout and repeated while the failure could still clear.
     *
     * The S3 client has no request timeout of its own, so a hung write would stall the poll loop
     * past Kafka's max.poll.interval.ms and evict the pod. The timeout aborts the request instead,
     * and the abort is retriable because it says nothing about whether S3 would accept the object.
     *
     * Every key this class writes is either unique to one call or created under IfNoneMatch, so a
     * repeated request writes the same bytes to the same key, or reports the conflict that
     * writeUrlImage already reads as a result. Retrying is therefore safe for all three commands.
     */
    private async send(command: PutObjectCommand | DeleteObjectCommand): Promise<void> {
        const startedAtMs = performance.now()
        for (let attempt = 1; ; attempt++) {
            const controller = new AbortController()
            let timedOut = false
            let failure: unknown
            const timer = setTimeout(() => {
                timedOut = true
                controller.abort()
            }, this.writeTimeoutMs)
            try {
                await this.s3.send(command, { abortSignal: controller.signal })
                return
            } catch (error) {
                failure = error
            } finally {
                clearTimeout(timer)
            }
            if (
                attempt >= S3_WRITE_MAX_ATTEMPTS ||
                performance.now() - startedAtMs >= S3_WRITE_RETRY_BUDGET_MS ||
                !(timedOut || isTransientS3Failure(failure))
            ) {
                throw failure
            }
            // The status is the one thing the shutdown path cannot report, and it is what separates
            // an overloaded bucket from a request S3 refused.
            logger.warn('🔁', 'image_scrub_s3_write_retry', {
                key: command.input.Key,
                attempt,
                timedOut,
                status: s3HttpStatus(failure),
                errorName: s3ErrorName(failure),
            })
            await this.sleep(retryBackoffMs(attempt))
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
        try {
            await this.send(
                new PutObjectCommand({
                    Bucket: this.bucket,
                    Key: `${this.prefix}/index/${stamp}.parquet`,
                    Body: indexBody,
                    ContentType: 'application/vnd.apache.parquet',
                })
            )
        } catch (e) {
            // Reclaim the orphaned shard so a repeatedly-failing index write doesn't leak a fresh blob per replay.
            await this.send(new DeleteObjectCommand({ Bucket: this.bucket, Key: shardKey })).catch(() => {})
            throw e
        }
        return { shard: shardKey, bytes: offset }
    }

    public async writeUrlImage(image: ScrubbedUrlImage): Promise<UrlImageWriteOutcome> {
        if (
            !Number.isSafeInteger(image.sourcePartition) ||
            image.sourcePartition < 0 ||
            !Number.isSafeInteger(image.sourceOffset) ||
            image.sourceOffset < 0
        ) {
            throw new Error('URL image source position must contain non-negative safe integers')
        }
        const key = `${this.prefix}/url/${image.hash}`
        for (let attempt = 0; attempt < URL_WRITE_MAX_ATTEMPTS; attempt++) {
            try {
                await this.send(
                    new PutObjectCommand({
                        Bucket: this.bucket,
                        Key: key,
                        Body: image.bytes,
                        ContentType: 'application/octet-stream',
                        Metadata: {
                            [URL_SOURCE_PARTITION_METADATA]: String(image.sourcePartition),
                            [URL_SOURCE_OFFSET_METADATA]: String(image.sourceOffset),
                        },
                        IfNoneMatch: '*',
                    })
                )
                return 'created'
            } catch (error) {
                if (isPreconditionFailed(error)) {
                    return 'already_exists'
                }
                if (isConditionalRequestConflict(error)) {
                    continue
                }
                throw error
            }
        }
        throw new Error(`URL image ${image.hash} conditional create did not converge`)
    }
}

function s3HttpStatus(error: unknown): number | undefined {
    if (typeof error !== 'object' || error === null) {
        return undefined
    }
    const metadata = (error as { $metadata?: { httpStatusCode?: unknown } }).$metadata
    return typeof metadata?.httpStatusCode === 'number' ? metadata.httpStatusCode : undefined
}

function s3ErrorName(error: unknown): string {
    return typeof error === 'object' && error !== null && typeof (error as { name?: unknown }).name === 'string'
        ? String((error as { name: string }).name)
        : ''
}

function isPreconditionFailed(error: unknown): boolean {
    return s3HttpStatus(error) === 412 || s3ErrorName(error) === 'PreconditionFailed'
}

function isConditionalRequestConflict(error: unknown): boolean {
    return s3HttpStatus(error) === 409 || s3ErrorName(error) === 'ConditionalRequestConflict'
}

/**
 * Whether repeating the request could produce a different answer.
 *
 * A 5xx or a 429 is S3 declining to serve the request now. An error that carries no HTTP status
 * never reached a response at all, which covers a dropped socket, a DNS failure, and an error body
 * the SDK could not match to a known shape. The two conditional outcomes are excluded because
 * writeUrlImage reads them as results rather than as failures.
 */
function isTransientS3Failure(error: unknown): boolean {
    if (isPreconditionFailed(error) || isConditionalRequestConflict(error)) {
        return false
    }
    const status = s3HttpStatus(error)
    return status === undefined || status >= 500 || status === 429
}

/** Full jitter, so the pods that one S3 slowdown hits together do not retry in lockstep. */
function retryBackoffMs(attempt: number): number {
    return Math.round(Math.random() * Math.min(S3_WRITE_RETRY_MAX_BACKOFF_MS, S3_WRITE_RETRY_BASE_MS * 2 ** attempt))
}
