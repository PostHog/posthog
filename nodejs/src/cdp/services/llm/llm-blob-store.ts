import { GetObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'

import { logger } from '~/common/utils/logger'

// Object-storage seam for spilling large LLM payloads out of cyclotron_jobs.state, so the hot
// shared table stays small (the RFC's Postgres-size constraint). An interface so the executor can
// be tested with an in-memory fake and the real path uses S3-compatible storage (SeaweedFS).

export interface LlmBlobStore {
    // Store a blob under a key. Overwrites are fine - keys are derived from (team, job, action, nonce).
    put(key: string, body: string): Promise<void>
    // Fetch a previously stored blob. Throws if the key is missing.
    get(key: string): Promise<string>
}

// S3-compatible implementation (SeaweedFS in dev; any S3 store in prod). The AWS SDK has no
// per-request timeout, so each call is wrapped in an AbortController, mirroring the session-replay
// writers.
export class S3LlmBlobStore implements LlmBlobStore {
    constructor(
        private s3: S3Client,
        private bucket: string,
        private timeoutMs: number
    ) {}

    public async put(key: string, body: string): Promise<void> {
        await this.send(
            new PutObjectCommand({ Bucket: this.bucket, Key: key, Body: body, ContentType: 'application/json' })
        )
    }

    public async get(key: string): Promise<string> {
        const controller = new AbortController()
        const timer = setTimeout(() => controller.abort(), this.timeoutMs)
        try {
            const response = await this.s3.send(new GetObjectCommand({ Bucket: this.bucket, Key: key }), {
                abortSignal: controller.signal,
            })
            if (!response.Body) {
                throw new Error(`LLM blob not found: ${key}`)
            }
            return await response.Body.transformToString()
        } finally {
            clearTimeout(timer)
        }
    }

    private async send(command: PutObjectCommand): Promise<void> {
        const controller = new AbortController()
        const timer = setTimeout(() => controller.abort(), this.timeoutMs)
        try {
            await this.s3.send(command, { abortSignal: controller.signal })
        } finally {
            clearTimeout(timer)
        }
    }
}

// Builds the LLM blob store from env, defaulting to the local SeaweedFS S3 endpoint. Returns null
// when object storage isn't configured - the executor then inlines completions (fine for small
// outputs; large ones just bloat state until storage is wired, which the spill is there to avoid).
export function buildLlmBlobStore(): LlmBlobStore | null {
    const endpoint = process.env.CDP_LLM_S3_ENDPOINT ?? 'http://localhost:8333'
    const region = process.env.CDP_LLM_S3_REGION ?? 'us-east-1'
    const bucket = process.env.CDP_LLM_S3_BUCKET ?? 'posthog'
    const accessKeyId = process.env.CDP_LLM_S3_ACCESS_KEY_ID ?? 'any'
    const secretAccessKey = process.env.CDP_LLM_S3_SECRET_ACCESS_KEY ?? 'any'
    const timeoutMs = Number(process.env.CDP_LLM_S3_TIMEOUT_MS ?? 30_000)

    if (!endpoint || !region || !bucket) {
        logger.warn('⚠️', 'LLM object storage is not configured - large completions will not be spilled')
        return null
    }

    const s3 = new S3Client({
        region,
        endpoint,
        forcePathStyle: true, // required for SeaweedFS / MinIO
        credentials: { accessKeyId, secretAccessKey },
    })
    return new S3LlmBlobStore(s3, bucket, timeoutMs)
}

// Test / local double. Not for production use.
export class InMemoryLlmBlobStore implements LlmBlobStore {
    public readonly blobs = new Map<string, string>()

    public put(key: string, body: string): Promise<void> {
        this.blobs.set(key, body)
        return Promise.resolve()
    }

    public get(key: string): Promise<string> {
        const body = this.blobs.get(key)
        if (body === undefined) {
            return Promise.reject(new Error(`LLM blob not found: ${key}`))
        }
        return Promise.resolve(body)
    }
}
