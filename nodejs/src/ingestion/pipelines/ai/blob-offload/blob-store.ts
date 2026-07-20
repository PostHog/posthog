import { CopyObjectCommand, HeadObjectCommand, PutObjectCommand, S3Client, S3ClientConfig } from '@aws-sdk/client-s3'

import { aiBlobOffloadS3Duration, aiBlobOffloadS3Errors } from '~/ingestion/pipelines/ai/metrics'

export type EnsureStoredOutcome = 'uploaded' | 'fresh' | 'touched'

export interface BlobStore {
    ensureStored(teamId: number, blob: { hash: string; bytes: Buffer; mime: string }): Promise<EnsureStoredOutcome>
}

interface S3BlobStoreConfig {
    bucket: string
    prefix: string
    touchAfterMs: number
}

export class S3BlobStore implements BlobStore {
    constructor(
        private s3: S3Client,
        private config: S3BlobStoreConfig
    ) {}

    private key(teamId: number, hash: string): string {
        return `${this.config.prefix}${teamId}/sha256/${hash}`
    }

    private async timed<T>(
        op: 'head' | 'put' | 'copy',
        fn: () => Promise<T>,
        shouldCountError?: (error: unknown) => boolean
    ): Promise<T> {
        const timer = aiBlobOffloadS3Duration.labels(op).startTimer()
        try {
            return await fn()
        } catch (error) {
            if (!shouldCountError || shouldCountError(error)) {
                aiBlobOffloadS3Errors.labels(op).inc()
            }
            throw error
        } finally {
            timer()
        }
    }

    async ensureStored(
        teamId: number,
        blob: { hash: string; bytes: Buffer; mime: string }
    ): Promise<EnsureStoredOutcome> {
        const Bucket = this.config.bucket
        const Key = this.key(teamId, blob.hash)

        let lastModified: Date | undefined
        try {
            const head = await this.timed(
                'head',
                () => this.s3.send(new HeadObjectCommand({ Bucket, Key })),
                (error): boolean => !(error instanceof Error && error.name === 'NotFound')
            )
            lastModified = head.LastModified
        } catch (error) {
            if (error instanceof Error && error.name === 'NotFound') {
                await this.timed('put', () =>
                    this.s3.send(new PutObjectCommand({ Bucket, Key, Body: blob.bytes, ContentType: blob.mime }))
                )
                return 'uploaded'
            }
            throw error
        }

        const age = Date.now() - (lastModified?.getTime() ?? 0)
        if (age <= this.config.touchAfterMs) {
            return 'fresh'
        }
        // Self-copy resets the object's creation date, which the bucket's 31-day
        // lifecycle rule keys on — every object outlives its last reference by ≥30d.
        await this.timed('copy', () =>
            this.s3.send(
                new CopyObjectCommand({
                    Bucket,
                    Key,
                    CopySource: `${Bucket}/${Key}`,
                    MetadataDirective: 'REPLACE',
                    ContentType: blob.mime,
                })
            )
        )
        return 'touched'
    }
}

export interface AiBlobS3Config {
    AI_BLOB_S3_BUCKET: string
    AI_BLOB_S3_PREFIX: string
    AI_BLOB_S3_ENDPOINT: string
    AI_BLOB_S3_REGION: string
    AI_BLOB_S3_ACCESS_KEY_ID: string
    AI_BLOB_S3_SECRET_ACCESS_KEY: string
    AI_BLOB_OFFLOAD_TOUCH_AFTER_HOURS: number
}

export function buildAiBlobStore(config: AiBlobS3Config): S3BlobStore | null {
    if (!config.AI_BLOB_S3_BUCKET) {
        return null
    }
    const s3Config: S3ClientConfig = { region: config.AI_BLOB_S3_REGION }
    if (config.AI_BLOB_S3_ENDPOINT) {
        s3Config.endpoint = config.AI_BLOB_S3_ENDPOINT
        s3Config.forcePathStyle = true
    }
    if (config.AI_BLOB_S3_ACCESS_KEY_ID && config.AI_BLOB_S3_SECRET_ACCESS_KEY) {
        s3Config.credentials = {
            accessKeyId: config.AI_BLOB_S3_ACCESS_KEY_ID,
            secretAccessKey: config.AI_BLOB_S3_SECRET_ACCESS_KEY,
        }
    }
    return new S3BlobStore(new S3Client(s3Config), {
        bucket: config.AI_BLOB_S3_BUCKET,
        prefix: config.AI_BLOB_S3_PREFIX,
        touchAfterMs: config.AI_BLOB_OFFLOAD_TOUCH_AFTER_HOURS * 3600 * 1000,
    })
}
