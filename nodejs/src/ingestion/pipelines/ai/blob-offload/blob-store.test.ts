import { CopyObjectCommand, HeadObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'

import { aiBlobOffloadS3Errors } from '~/ingestion/pipelines/ai/metrics'

import { S3BlobStore, buildAiBlobStore } from './blob-store'

const HASH = 'b'.repeat(64)
const BLOB = { hash: HASH, bytes: Buffer.from('payload'), mime: 'image/png' }
const NOW = new Date('2026-07-16T12:00:00Z')

function notFound(): Error {
    const error = new Error('not found')
    error.name = 'NotFound'
    return error
}

describe('S3BlobStore', () => {
    let s3: S3Client
    let send: jest.SpyInstance

    beforeEach(() => {
        jest.useFakeTimers().setSystemTime(NOW)
        s3 = new S3Client({ region: 'us-east-1' })
        send = jest.spyOn(s3, 'send')
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    function store(): S3BlobStore {
        return new S3BlobStore(s3, { bucket: 'blobs', prefix: 'p/', touchAfterMs: 20 * 3600 * 1000, timeoutMs: 30000 })
    }

    it('uploads on miss with the content-addressed key and mime', async () => {
        send.mockRejectedValueOnce(notFound()).mockResolvedValueOnce({})
        await expect(store().ensureStored(2, BLOB)).resolves.toBe('uploaded')
        expect(send.mock.calls[0][0]).toBeInstanceOf(HeadObjectCommand)
        const put = send.mock.calls[1][0]
        expect(put).toBeInstanceOf(PutObjectCommand)
        expect(put.input).toMatchObject({ Bucket: 'blobs', Key: `p/2/sha256/${HASH}`, ContentType: 'image/png' })
        expect(Buffer.from(put.input.Body).equals(BLOB.bytes)).toBe(true)
    })

    it('does nothing when the object is fresh', async () => {
        send.mockResolvedValueOnce({ LastModified: new Date(NOW.getTime() - 3600 * 1000) })
        await expect(store().ensureStored(2, BLOB)).resolves.toBe('fresh')
        expect(send).toHaveBeenCalledTimes(1)
    })

    it('self-copies to reset the lifecycle clock when the object is stale', async () => {
        send.mockResolvedValueOnce({ LastModified: new Date(NOW.getTime() - 25 * 3600 * 1000) }).mockResolvedValueOnce(
            {}
        )
        await expect(store().ensureStored(2, BLOB)).resolves.toBe('touched')
        const copy = send.mock.calls[1][0]
        expect(copy).toBeInstanceOf(CopyObjectCommand)
        expect(copy.input).toMatchObject({
            Bucket: 'blobs',
            Key: `p/2/sha256/${HASH}`,
            CopySource: `blobs/p/2/sha256/${HASH}`,
            MetadataDirective: 'REPLACE',
            ContentType: 'image/png',
        })
    })

    it('URI-encodes CopySource so prefixes with special characters can refresh', async () => {
        const spaced = new S3BlobStore(s3, {
            bucket: 'blobs',
            prefix: 'ai blobs/v+1/',
            touchAfterMs: 20 * 3600 * 1000,
            timeoutMs: 30000,
        })
        send.mockResolvedValueOnce({ LastModified: new Date(NOW.getTime() - 25 * 3600 * 1000) }).mockResolvedValueOnce(
            {}
        )
        await expect(spaced.ensureStored(2, BLOB)).resolves.toBe('touched')
        const copy = send.mock.calls[1][0]
        expect(copy.input.Key).toBe(`ai blobs/v+1/2/sha256/${HASH}`)
        expect(copy.input.CopySource).toBe(`blobs/ai%20blobs/v%2B1/2/sha256/${HASH}`)
    })

    it('treats a HEAD response without LastModified as stale', async () => {
        send.mockResolvedValueOnce({}).mockResolvedValueOnce({})
        await expect(store().ensureStored(2, BLOB)).resolves.toBe('touched')
    })

    it.each([
        ['HEAD', 0],
        ['PUT after miss', 1],
    ])('propagates non-NotFound failures (%s)', async (_name, failingCall) => {
        const boom = new Error('s3 down')
        if (failingCall === 0) {
            send.mockRejectedValueOnce(boom)
        } else {
            send.mockRejectedValueOnce(notFound()).mockRejectedValueOnce(boom)
        }
        await expect(store().ensureStored(2, BLOB)).rejects.toThrow('s3 down')
    })

    it('does not count HEAD NotFound as S3 failure (normal miss flow) but counts genuine HEAD errors', async () => {
        aiBlobOffloadS3Errors.reset()
        let headErrors = (await aiBlobOffloadS3Errors.get()).values.find((v) => v.labels.op === 'head')?.value ?? 0
        expect(headErrors).toBe(0)

        send.mockRejectedValueOnce(notFound()).mockResolvedValueOnce({})
        const outcome = await store().ensureStored(2, BLOB)
        expect(outcome).toBe('uploaded')

        headErrors = (await aiBlobOffloadS3Errors.get()).values.find((v) => v.labels.op === 'head')?.value ?? 0
        expect(headErrors).toBe(0)

        send.mockRejectedValueOnce(new Error('s3 down'))
        await expect(store().ensureStored(2, BLOB)).rejects.toThrow('s3 down')

        headErrors = (await aiBlobOffloadS3Errors.get()).values.find((v) => v.labels.op === 'head')?.value ?? 0
        expect(headErrors).toBe(1)
    })

    it('returns null when the bucket is unset (offload disabled)', () => {
        const base = {
            AI_BLOB_S3_BUCKET: 'blobs',
            AI_BLOB_S3_PREFIX: '',
            AI_BLOB_S3_ENDPOINT: '',
            AI_BLOB_S3_REGION: 'us-east-1',
            AI_BLOB_S3_ACCESS_KEY_ID: '',
            AI_BLOB_S3_SECRET_ACCESS_KEY: '',
            AI_BLOB_S3_TIMEOUT_MS: 30000,
            AI_BLOB_OFFLOAD_TOUCH_AFTER_HOURS: 20,
        }
        expect(buildAiBlobStore({ ...base, AI_BLOB_S3_BUCKET: '' })).toBeNull()
    })

    it('builds a store when the bucket is set', () => {
        const base = {
            AI_BLOB_S3_BUCKET: 'blobs',
            AI_BLOB_S3_PREFIX: '',
            AI_BLOB_S3_ENDPOINT: '',
            AI_BLOB_S3_REGION: 'us-east-1',
            AI_BLOB_S3_ACCESS_KEY_ID: '',
            AI_BLOB_S3_SECRET_ACCESS_KEY: '',
            AI_BLOB_S3_TIMEOUT_MS: 30000,
            AI_BLOB_OFFLOAD_TOUCH_AFTER_HOURS: 20,
        }
        expect(buildAiBlobStore(base)).not.toBeNull()
    })

    // 31d bucket lifecycle − 30d row TTL leaves at most 24h of touch slack; a
    // larger window silently produces pointers that outlive their objects.
    it('rejects a touch-after window that could outlive the lifecycle safety margin', () => {
        const base = {
            AI_BLOB_S3_BUCKET: 'blobs',
            AI_BLOB_S3_PREFIX: '',
            AI_BLOB_S3_ENDPOINT: '',
            AI_BLOB_S3_REGION: 'us-east-1',
            AI_BLOB_S3_ACCESS_KEY_ID: '',
            AI_BLOB_S3_SECRET_ACCESS_KEY: '',
            AI_BLOB_S3_TIMEOUT_MS: 30000,
            AI_BLOB_OFFLOAD_TOUCH_AFTER_HOURS: 48,
        }
        expect(() => buildAiBlobStore(base)).toThrow()
    })
})
