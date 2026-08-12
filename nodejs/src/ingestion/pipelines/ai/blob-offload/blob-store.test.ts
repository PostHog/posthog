import {
    CopyObjectCommand,
    HeadObjectCommand,
    NoSuchKey,
    NotFound,
    PutObjectCommand,
    S3Client,
    S3ServiceException,
} from '@aws-sdk/client-s3'

import { aiBlobOffloadS3Errors } from '~/ingestion/pipelines/ai/metrics'

import { BlobStoreError, S3BlobStore, buildAiBlobStore } from './blob-store'

const HASH = 'b'.repeat(64)
const BLOB = { hash: HASH, bytes: Buffer.from('payload'), mime: 'image/png' }
const NOW = new Date('2026-07-16T12:00:00Z')

function notFound(): NotFound {
    return new NotFound({ $metadata: {}, message: 'not found' })
}

/** Unmodeled S3 errors deserialize into the generic S3ServiceException with the code in `.name`. */
function s3Error(name: string): S3ServiceException {
    return new S3ServiceException({ name, $fault: 'client', $metadata: {}, message: name })
}

async function captureError(promise: Promise<unknown>): Promise<BlobStoreError> {
    try {
        await promise
    } catch (error) {
        return error as BlobStoreError
    }
    throw new Error('expected rejection')
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

    // The error contract the upload step's retry wrapper depends on: every
    // failure surfaces as BlobStoreError with the provider error as cause.
    // Only provably event-specific failures are non-retriable (-> DLQ);
    // everything else is retriable so transient errors retry and env-wide
    // problems crash loudly after exhaustion instead of dead-lettering a lane.
    it.each([
        ['SlowDown (throttling)', (): Error => s3Error('SlowDown')],
        ['InternalError (5xx)', (): Error => s3Error('InternalError')],
        ['RequestTimeout', (): Error => s3Error('RequestTimeout')],
        ['AccessDenied', (): Error => s3Error('AccessDenied')],
        ['NoSuchBucket', (): Error => s3Error('NoSuchBucket')],
        ['a non-S3 network error', (): Error => new Error('connect ECONNREFUSED')],
    ])('wraps %s as a retriable store error', async (_name, makeError) => {
        const cause = makeError()
        send.mockRejectedValueOnce(cause)
        const error = await captureError(store().ensureStored(2, BLOB))
        expect(error).toBeInstanceOf(BlobStoreError)
        expect(error.isRetriable).toBe(true)
        expect(error.cause).toBe(cause)
    })

    it.each([['EntityTooLarge'], ['MetadataTooLarge']])(
        'wraps %s as non-retriable — determined by the event, retrying cannot fix it',
        async (name) => {
            const cause = s3Error(name)
            send.mockRejectedValueOnce(notFound()).mockRejectedValueOnce(cause)
            const error = await captureError(store().ensureStored(2, BLOB))
            expect(error).toBeInstanceOf(BlobStoreError)
            expect(error.isRetriable).toBe(false)
            expect(error.cause).toBe(cause)
        }
    )

    it('never interprets event-specific codes on errors that are not S3ServiceException', async () => {
        const impostor = new Error('EntityTooLarge')
        impostor.name = 'EntityTooLarge'
        send.mockRejectedValueOnce(notFound()).mockRejectedValueOnce(impostor)
        const error = await captureError(store().ensureStored(2, BLOB))
        expect(error.isRetriable).toBe(true)
    })

    it('wraps a copy-race NoSuchKey as retriable, and a rerun self-heals via a fresh head', async () => {
        const s = store()
        const race = new NoSuchKey({ $metadata: {}, message: 'gone' })
        send.mockResolvedValueOnce({ LastModified: new Date(NOW.getTime() - 25 * 3600 * 1000) })
            .mockRejectedValueOnce(race)
            .mockRejectedValueOnce(notFound())
            .mockResolvedValueOnce({})
        // The object expired between head and copy: retriable, so the step
        // retry reruns ensureStored, whose fresh head now misses and re-uploads.
        const raceError = await captureError(s.ensureStored(2, BLOB))
        expect(raceError).toBeInstanceOf(BlobStoreError)
        expect(raceError.isRetriable).toBe(true)
        expect(raceError.cause).toBe(race)
        await expect(s.ensureStored(2, BLOB)).resolves.toBe('uploaded')
        expect(send.mock.calls[3][0]).toBeInstanceOf(PutObjectCommand)
    })

    it('healthcheck self-tests every operation ensureStored performs against the sentinel key', async () => {
        send.mockResolvedValue({})
        await expect(store().healthcheck()).resolves.toBeUndefined()
        expect(send.mock.calls).toHaveLength(3)
        const [put, head, copy] = send.mock.calls.map((call) => call[0])
        expect(put).toBeInstanceOf(PutObjectCommand)
        expect(put.input).toMatchObject({ Bucket: 'blobs', Key: 'p/_health/probe' })
        expect(head).toBeInstanceOf(HeadObjectCommand)
        expect(head.input).toMatchObject({ Key: 'p/_health/probe' })
        expect(copy).toBeInstanceOf(CopyObjectCommand)
        expect(copy.input).toMatchObject({ Key: 'p/_health/probe', CopySource: 'blobs/p/_health/probe' })
    })

    it.each([
        ['put', 0],
        ['head', 1],
        ['copy', 2],
    ])('healthcheck surfaces a %s failure as a retriable store error naming the op', async (op, failingCall) => {
        const cause = s3Error('AccessDenied')
        for (let i = 0; i < failingCall; i++) {
            send.mockResolvedValueOnce({})
        }
        send.mockRejectedValueOnce(cause)
        const error = await captureError(store().healthcheck())
        expect(error).toBeInstanceOf(BlobStoreError)
        expect(error.message).toBe(
            `AI blob store healthcheck failed (${op}) for bucket "blobs": AccessDenied: AccessDenied`
        )
        expect(error.isRetriable).toBe(true)
        expect(error.cause).toBe(cause)
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
