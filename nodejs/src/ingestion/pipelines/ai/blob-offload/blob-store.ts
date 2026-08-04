import {
    CopyObjectCommand,
    HeadObjectCommand,
    NotFound,
    PutObjectCommand,
    S3Client,
    S3ClientConfig,
    S3ServiceException,
} from '@aws-sdk/client-s3'

import { Component } from '~/ingestion/common/scopes'
import { aiBlobOffloadS3Duration, aiBlobOffloadS3Errors } from '~/ingestion/pipelines/ai/metrics'

export type EnsureStoredOutcome = 'uploaded' | 'fresh' | 'touched'

/**
 * The only error type blob store implementations throw. Encapsulates the
 * provider's error taxonomy behind one framework-facing flag:
 *
 * - `isRetriable: false` — this blob can never be stored; the failure is
 *   determined by the event's own content. The pipeline's step-retry wrapper
 *   turns it into a DLQ sub-result, so just the affected event dead-letters.
 * - `isRetriable: true` — worth retrying: transient (timeouts, throttling,
 *   5xx, networking) or environment-wide (auth, missing bucket) failures.
 *   The retry wrapper retries and, on exhaustion, crashes the consumer —
 *   an environment-wide problem must fail loudly, never silently divert a
 *   lane's data to the DLQ.
 *
 * The underlying provider error is always preserved as `cause`.
 */
export class BlobStoreError extends Error {
    constructor(
        message: string,
        readonly isRetriable: boolean,
        options?: { cause?: unknown }
    ) {
        super(message, options)
        this.name = 'BlobStoreError'
    }
}

/**
 * Embed the provider error's name in the wrapper message: the framework's log
 * path (withStepRetry -> logger.error) serializes message and stack manually
 * and drops `cause` chains, so the embedded name is the greppable
 * discriminator in logs during incidents — AWS messages often omit the code.
 */
function describeProviderError(error: unknown): string {
    return error instanceof Error ? `${error.name}: ${error.message}` : String(error)
}

export interface BlobStore {
    /**
     * Ensure the blob is durably stored. Failures are thrown exclusively as
     * {@link BlobStoreError} — callers never see provider error types.
     */
    ensureStored(teamId: number, blob: { hash: string; bytes: Buffer; mime: string }): Promise<EnsureStoredOutcome>
}

interface S3BlobStoreConfig {
    bucket: string
    prefix: string
    touchAfterMs: number
    timeoutMs: number
}

/**
 * AWS error names that are provably caused by the content of the request —
 * deterministic per event, so no retry (and no environment change) can ever
 * make them succeed. Translated to `isRetriable: false`:
 *
 * - `EntityTooLarge`: the PUT body exceeds S3's single-request object size
 *   limit — a property of this event's blob bytes.
 * - `MetadataTooLarge`: the request metadata/headers exceed S3's limit — the
 *   only per-request headers we send are derived from the blob's detected
 *   mime (Content-Type on put and copy), so this too is determined by the
 *   event.
 *
 * Deliberately narrow: everything else translates to `isRetriable: true`,
 * because it is either transient (retry owns it) or environment-wide
 * (AccessDenied, NoSuchBucket, credentials — those crash after retries, and
 * the startup healthcheck catches them before traffic). `KeyTooLongError` is
 * intentionally not here: our keys are prefix + team id + fixed-length hash,
 * so an over-long key is configuration, not event content.
 */
const EVENT_SPECIFIC_S3_ERRORS = new Set(['EntityTooLarge', 'MetadataTooLarge'])

export class S3BlobStore implements BlobStore {
    constructor(
        private s3: S3Client,
        private config: S3BlobStoreConfig
    ) {}

    private key(teamId: number, hash: string): string {
        return `${this.config.prefix}${teamId}/sha256/${hash}`
    }

    /** Translate an AWS failure into the store's error type at the public boundary. */
    private toStoreError(error: unknown): BlobStoreError {
        // The two event-specific codes are not modeled by the SDK (they
        // deserialize into the generic S3ServiceException with the code in
        // `.name`), so after narrowing to S3ServiceException the name check is
        // the only handle on them. Names on non-S3 errors are never interpreted.
        const isRetriable = !(error instanceof S3ServiceException && EVENT_SPECIFIC_S3_ERRORS.has(error.name))
        return new BlobStoreError(`S3 blob store failure: ${describeProviderError(error)}`, isRetriable, {
            cause: error,
        })
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

    /**
     * Startup self-test: exercises every S3 operation `ensureStored` performs
     * (PUT, HEAD, self-COPY) against a sentinel key under the configured
     * prefix, so missing permissions, a bad bucket, or no connectivity fail
     * the deployment at scope start — before any traffic — instead of
     * crash-looping the lane on the first blob-carrying event. Sentinel
     * collisions between pods are harmless, and the bucket lifecycle cleans
     * the object up like any blob.
     */
    async healthcheck(): Promise<void> {
        const Bucket = this.config.bucket
        const Key = `${this.config.prefix}_health/probe`
        const abort = (): { abortSignal: AbortSignal } => ({
            abortSignal: AbortSignal.timeout(this.config.timeoutMs),
        })
        const probe = async (op: string, fn: () => Promise<unknown>): Promise<void> => {
            try {
                await fn()
            } catch (error) {
                throw new BlobStoreError(
                    `AI blob store healthcheck failed (${op}) for bucket "${Bucket}": ${describeProviderError(error)}`,
                    true,
                    { cause: error }
                )
            }
        }
        await probe('put', () =>
            this.s3.send(
                new PutObjectCommand({ Bucket, Key, Body: Buffer.from('ok'), ContentType: 'text/plain' }),
                abort()
            )
        )
        await probe('head', () => this.s3.send(new HeadObjectCommand({ Bucket, Key }), abort()))
        await probe('copy', () =>
            this.s3.send(
                new CopyObjectCommand({
                    Bucket,
                    Key,
                    CopySource: `${Bucket}/${Key.split('/').map(encodeURIComponent).join('/')}`,
                    MetadataDirective: 'REPLACE',
                    ContentType: 'text/plain',
                }),
                abort()
            )
        )
    }

    async ensureStored(
        teamId: number,
        blob: { hash: string; bytes: Buffer; mime: string }
    ): Promise<EnsureStoredOutcome> {
        try {
            return await this.ensureStoredS3(teamId, blob)
        } catch (error) {
            throw this.toStoreError(error)
        }
    }

    /** Raw S3 flow; AWS errors escape here and are translated by ensureStored. */
    private async ensureStoredS3(
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
                (error): boolean => !(error instanceof NotFound)
            )
            lastModified = head.LastModified
        } catch (error) {
            if (error instanceof NotFound) {
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

/**
 * Scope entry for the AI blob store. `start()` builds the store from config
 * (null when no bucket is configured — offload disabled) and runs its startup
 * healthcheck, mirroring the Kafka consumer's connect-at-start contract: an
 * unreachable bucket (bad credentials, missing bucket, no route) fails
 * startup before any traffic is consumed, instead of crash-looping on the
 * first blob-carrying event. The value is wrapped (`{ store }`) because
 * container entries must be objects and the store may be null.
 */
export class AiBlobStoreComponent implements Component<{ store: BlobStore | null }> {
    constructor(private readonly config: AiBlobS3Config) {}

    async start(): Promise<{ value: { store: BlobStore | null }; stop: () => Promise<void> }> {
        const store = buildAiBlobStore(this.config)
        if (store) {
            await store.healthcheck()
        }
        return { value: { store }, stop: () => Promise.resolve() }
    }
}
