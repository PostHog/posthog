import {
    CreateBucketCommand,
    DeleteObjectCommand,
    GetObjectCommand,
    HeadObjectCommand,
    S3Client,
} from '@aws-sdk/client-s3'

import { BlobStoreError, S3BlobStore } from './blob-store'

jest.setTimeout(30000)

// The dev stack's S3-compatible store: the SeaweedFS `seaweedfs` service on
// :8333 — the same instance and bucket session replay v2 uses
// (SESSION_RECORDING_V2_S3_*, whose defaults this connection config mirrors).
// The service sits behind the replay/agents compose profiles, so the Node.js
// Tests CI job starts it explicitly (see ci-nodejs.yml); locally run
// `docker compose -f docker-compose.dev.yml up seaweedfs -d --wait`.
// The shared `posthog` bucket is deliberate: SeaweedFS maps each bucket to a
// collection with its own volume slots, and the dev node's 8 slots are already
// allocated — a dedicated test bucket would hang on volume assignment.
const ENDPOINT = 'http://localhost:8333'
const BUCKET = 'posthog'
// URL-significant characters on purpose (the percent-encoded CopySource was a
// prior review finding, and only a real implementation can falsify it); a
// per-run segment keeps reruns from seeing earlier objects.
const PREFIX = `ai blobs it/v+1/${Date.now()}/`
const TIMEOUT_MS = 10000

describe('S3BlobStore (integration)', () => {
    let s3: S3Client
    const storedKeys: string[] = []

    const makeStore = (touchAfterMs: number): S3BlobStore =>
        new S3BlobStore(s3, { bucket: BUCKET, prefix: PREFIX, touchAfterMs, timeoutMs: TIMEOUT_MS })

    const makeBlob = (suffix: string): { hash: string; bytes: Buffer; mime: string } => {
        const hash = `it-${Date.now()}-${suffix}`
        storedKeys.push(`${PREFIX}2/sha256/${hash}`)
        return { hash, bytes: Buffer.from(`payload-${suffix}`), mime: 'image/png' }
    }

    const keyFor = (blob: { hash: string }): string => `${PREFIX}2/sha256/${blob.hash}`

    beforeAll(async () => {
        s3 = new S3Client({
            region: 'us-east-1',
            endpoint: ENDPOINT,
            forcePathStyle: true,
            // The dev instance runs in open-access mode; any credentials sign.
            credentials: { accessKeyId: 'any', secretAccessKey: 'any' },
        })
        try {
            await s3.send(new CreateBucketCommand({ Bucket: BUCKET }))
        } catch (error) {
            const name = error instanceof Error ? error.name : ''
            if (name !== 'BucketAlreadyOwnedByYou' && name !== 'BucketAlreadyExists') {
                throw error
            }
        }
        storedKeys.push(`${PREFIX}_health/probe`)
    })

    afterAll(async () => {
        await Promise.all(
            storedKeys.map((Key) => s3.send(new DeleteObjectCommand({ Bucket: BUCKET, Key })).catch(() => undefined))
        )
        s3.destroy()
    })

    it('uploads a new blob on a real 404 head-miss and stores bytes with the detected mime', async () => {
        const store = makeStore(20 * 3600 * 1000)
        const blob = makeBlob('upload')

        // 'uploaded' proves the head-miss branch ran: `instanceof NotFound`
        // narrowed a real SeaweedFS 404, which no mocked SDK error can falsify.
        await expect(store.ensureStored(2, blob)).resolves.toBe('uploaded')

        const head = await s3.send(new HeadObjectCommand({ Bucket: BUCKET, Key: keyFor(blob) }))
        expect(head.ContentType).toBe('image/png')
        expect(head.ContentLength).toBe(blob.bytes.length)
        const got = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: keyFor(blob) }))
        const body = Buffer.from(await got.Body!.transformToByteArray())
        expect(body.equals(blob.bytes)).toBe(true)
    })

    it('returns fresh on an immediate second call without re-uploading', async () => {
        const store = makeStore(20 * 3600 * 1000)
        const blob = makeBlob('fresh')

        await expect(store.ensureStored(2, blob)).resolves.toBe('uploaded')
        await expect(store.ensureStored(2, blob)).resolves.toBe('fresh')
    })

    it('touches a stale object via a real self-copy with the percent-encoded CopySource', async () => {
        // touchAfterMs -1 forces the touch path deterministically even when
        // LastModified (second-truncated) rounds to "now".
        const store = makeStore(-1)
        const blob = makeBlob('touch')

        await expect(store.ensureStored(2, blob)).resolves.toBe('uploaded')
        // Validates CopyObject with MetadataDirective REPLACE and the
        // percent-encoded CopySource against a real implementation.
        await expect(store.ensureStored(2, blob)).resolves.toBe('touched')

        const head = await s3.send(new HeadObjectCommand({ Bucket: BUCKET, Key: keyFor(blob) }))
        expect(head.ContentType).toBe('image/png')
        expect(head.ContentLength).toBe(blob.bytes.length)
    })

    it('healthcheck self-test passes against the real bucket', async () => {
        await expect(makeStore(20 * 3600 * 1000).healthcheck()).resolves.toBeUndefined()
    })

    it('healthcheck fails with a retriable store error naming the op for a nonexistent bucket', async () => {
        const missing = new S3BlobStore(s3, {
            bucket: 'aio-blob-store-it-missing',
            prefix: PREFIX,
            touchAfterMs: 0,
            timeoutMs: TIMEOUT_MS,
        })
        const error = await missing.healthcheck().then(
            () => null,
            (e: BlobStoreError) => e
        )
        expect(error).toBeInstanceOf(BlobStoreError)
        expect(error!.isRetriable).toBe(true)
        expect(error!.message).toContain('failed (put) for bucket "aio-blob-store-it-missing"')
    })
})
