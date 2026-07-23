import { GetObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'

// Object-storage seam for spilling large parked-job payloads out of cyclotron_jobs.state, so the hot
// shared table stays small. Caller-agnostic: any long-running step that produces an oversized result
// (an LLM completion today, a task output tomorrow) keeps only a reference in state and stores the
// full payload here. An interface so callers can be tested with an in-memory fake and the real path
// uses S3-compatible storage.

export interface JobBlobStore {
    // Store a blob under a key. Overwrites are fine — keys are derived from the parked step identity.
    put(key: string, body: string): Promise<void>
    // Fetch a previously stored blob. Throws if the key is missing.
    get(key: string): Promise<string>
}

export interface JobBlobStoreConfig {
    endpoint: string
    region: string
    bucket: string
    accessKeyId: string
    secretAccessKey: string
    timeoutMs: number
}

// S3-compatible implementation. The AWS SDK has no per-request timeout, so each call is wrapped in an
// AbortController, mirroring the session-replay writers.
export class S3JobBlobStore implements JobBlobStore {
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
                throw new Error(`Parked-job blob not found: ${key}`)
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

// Builds an S3-backed blob store from explicit config (callers read their own env and pass it in).
// Returns null when object storage isn't configured — the caller then inlines results (fine for
// small outputs; large ones bloat state until storage is wired, which the spill is there to avoid).
export function buildJobBlobStore(config: JobBlobStoreConfig): JobBlobStore | null {
    if (!config.endpoint || !config.region || !config.bucket) {
        return null
    }
    const s3 = new S3Client({
        region: config.region,
        endpoint: config.endpoint,
        forcePathStyle: true, // required for SeaweedFS / MinIO
        credentials: { accessKeyId: config.accessKeyId, secretAccessKey: config.secretAccessKey },
    })
    return new S3JobBlobStore(s3, config.bucket, config.timeoutMs)
}

// Test / local double. Not for production use.
export class InMemoryJobBlobStore implements JobBlobStore {
    public readonly blobs = new Map<string, string>()

    public put(key: string, body: string): Promise<void> {
        this.blobs.set(key, body)
        return Promise.resolve()
    }

    public get(key: string): Promise<string> {
        const body = this.blobs.get(key)
        if (body === undefined) {
            return Promise.reject(new Error(`Parked-job blob not found: ${key}`))
        }
        return Promise.resolve(body)
    }
}
