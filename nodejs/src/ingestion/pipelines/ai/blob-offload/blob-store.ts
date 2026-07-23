import {
    CopyObjectCommand,
    HeadBucketCommand,
    HeadObjectCommand,
    PutObjectCommand,
    S3Client,
    S3ClientConfig,
} from '@aws-sdk/client-s3'

import { aiBlobOffloadS3Duration, aiBlobOffloadS3Errors } from '~/ingestion/pipelines/ai/metrics'

export type EnsureStoredOutcome = 'uploaded' | 'fresh' | 'touched'

/**
 * AWS error names that are provably caused by the content of the request —
 * deterministic per event, so no retry (and no environment change) can ever
 * make them succeed. They are tagged `isRetriable: false` so the pipeline's
 * step-retry wrapper dead-letters just the affected event instead of
 * crash-looping the consumer on it forever:
 *
 * - `EntityTooLarge`: the PUT body exceeds S3's single-request object size
 *   limit — a property of this event's blob bytes.
 * - `MetadataTooLarge`: the request metadata/headers exceed S3's limit — the
 *   only per-request headers we send are derived from the blob's detected
 *   mime (Content-Type on put and copy), so this too is determined by the
 *   event.
 *
 * Deliberately narrow. Everything else stays unclassified and crashes loudly
 * after retries, because it is either transient (timeouts, 5xx, networking —
 * retry owns those) or environment-wide (AccessDenied, NoSuchBucket,
 * credentials — dead-lettering those would silently divert the whole lane's
 * data during an infra incident; the startup healthcheck catches them before
 * traffic instead). `KeyTooLongError` is intentionally excluded: our keys are
 * prefix + team id + fixed-length hash, so an over-long key is configuration,
 * not event content.
 */
const EVENT_SPECIFIC_S3_ERRORS = new Set(['EntityTooLarge', 'MetadataTooLarge'])

function tagEventSpecificError(error: unknown): unknown {
    if (error instanceof Error && EVENT_SPECIFIC_S3_ERRORS.has(error.name)) {
        ;(error as Error & { isRetriable?: boolean }).isRetriable = false
    }
    return error
}

export interface BlobStore {
    ensureStored(teamId: number, blob: { hash: string; bytes: Buffer; mime: string }): Promise<EnsureStoredOutcome>
}

interface S3BlobStoreConfig {
    bucket: string
    prefix: string
    touchAfterMs: number
    timeoutMs: number
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
            throw tagEventSpecificError(error)
        } finally {
            timer()
        }
    }

    /**
     * Startup probe: one cheap HeadBucket verifying bucket existence,
     * credentials, and connectivity. Run at consumer scope start (like the
     * Kafka consumer's connect) so environment-wide S3 problems fail the
     * deployment before it consumes traffic, instead of crash-looping the
     * lane on the first blob-carrying event.
     */
    async healthcheck(): Promise<void> {
        try {
            await this.s3.send(new HeadBucketCommand({ Bucket: this.config.bucket }), {
                abortSignal: AbortSignal.timeout(this.config.timeoutMs),
            })
        } catch (error) {
            throw new Error(`AI blob store healthcheck failed for bucket "${this.config.bucket}"`, { cause: error })
        }
    }

    async ensureStored(
        teamId: number,
        blob: { hash: string; bytes: Buffer; mime: string }
    ): Promise<EnsureStoredOutcome> {
        const Bucket = this.config.bucket
        const Key = this.key(teamId, blob.hash)
        const abort = (): { abortSignal: AbortSignal } => ({
            abortSignal: AbortSignal.timeout(this.config.timeoutMs),
        })

        let lastModified: Date | undefined
        try {
            const head = await this.timed(
                'head',
                () => this.s3.send(new HeadObjectCommand({ Bucket, Key }), abort()),
                (error): boolean => !(error instanceof Error && error.name === 'NotFound')
            )
            lastModified = head.LastModified
        } catch (error) {
            if (error instanceof Error && error.name === 'NotFound') {
                await this.timed('put', () =>
                    this.s3.send(
                        new PutObjectCommand({ Bucket, Key, Body: blob.bytes, ContentType: blob.mime }),
                        abort()
                    )
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
        // S3 URL-decodes CopySource (unlike Key), so path segments must be percent-encoded.
        await this.timed('copy', () =>
            this.s3.send(
                new CopyObjectCommand({
                    Bucket,
                    Key,
                    CopySource: `${Bucket}/${Key.split('/').map(encodeURIComponent).join('/')}`,
                    MetadataDirective: 'REPLACE',
                    ContentType: blob.mime,
                }),
                abort()
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
    AI_BLOB_S3_TIMEOUT_MS: number
    AI_BLOB_OFFLOAD_TOUCH_AFTER_HOURS: number
}

// The 31-day bucket lifecycle must outlive touch age + the 30-day ai_events row TTL,
// or pointers in live rows would reference expired objects.
const MAX_TOUCH_AFTER_HOURS = 24

export function buildAiBlobStore(config: AiBlobS3Config): S3BlobStore | null {
    if (!config.AI_BLOB_S3_BUCKET) {
        return null
    }
    if (config.AI_BLOB_OFFLOAD_TOUCH_AFTER_HOURS > MAX_TOUCH_AFTER_HOURS) {
        throw new Error(
            `AI_BLOB_OFFLOAD_TOUCH_AFTER_HOURS must be at most ${MAX_TOUCH_AFTER_HOURS}, got ${config.AI_BLOB_OFFLOAD_TOUCH_AFTER_HOURS}`
        )
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
        timeoutMs: config.AI_BLOB_S3_TIMEOUT_MS,
    })
}
