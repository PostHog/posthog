import { CreateBucketCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { createHash, randomBytes } from 'node:crypto'
import { ServerResponse, createServer, request as httpRequest } from 'node:http'
import { AddressInfo } from 'node:net'

import { getDefaultCdpConfig } from '~/cdp/config'
import { FetchResponse, internalFetch } from '~/common/utils/request'

import {
    ATTACHMENT_LIFETIME_MS,
    AttachmentMissingError,
    AttachmentStoreUnavailableError,
    DAY_MS,
    S3AttachmentStore,
    UploadSlot,
    buildAttachmentStore,
    credentialsThatOutliveUploadUrls,
} from './attachment-store'

jest.setTimeout(30000)

const config = { ...getDefaultCdpConfig(), CDP_EMAIL_ATTACHMENTS_S3_PREFIX: `attachments-test/${Date.now()}` }
const BUCKET = config.CDP_EMAIL_ATTACHMENTS_S3_BUCKET
const MINUTE_MS = 60 * 1000
const BUCKET_CLOCK_PRECISION_MS = 1000

type TestFile = { bytes: Buffer; sha256: string }
type UploadUrl = Extract<UploadSlot, { status: 'upload' }>
type Present = Extract<UploadSlot, { status: 'present' }>

const file = (): TestFile => {
    const bytes = Buffer.from(`%PDF-1.4 ${randomBytes(16).toString('hex')}`)
    return { bytes, sha256: createHash('sha256').update(bytes).digest('hex') }
}

const put = (slot: UploadSlot, body: Buffer): Promise<FetchResponse> => {
    if (slot.status !== 'upload') {
        throw new Error(`expected an upload slot, got ${slot.status}`)
    }
    return internalFetch(slot.url, { method: slot.method, headers: slot.headers, body })
}

const minutesFromNow = (minutes: number): Date => new Date(Date.now() + minutes * MINUTE_MS)

const settledWithin = async <T>(ms: number, promise: Promise<T>): Promise<T> => {
    let timer: NodeJS.Timeout | undefined
    try {
        return await Promise.race([
            promise,
            new Promise<never>((_, reject) => {
                timer = setTimeout(() => reject(new Error(`still pending after ${ms} ms`)), ms)
            }),
        ])
    } finally {
        clearTimeout(timer)
    }
}

type FileBody = 'stall after its first byte' | 'change its last byte'
type BucketFault = FileBody | 'stall every copy'

type BucketProxy = { endpoint: string; bodyAnswered: Promise<void>; cut: () => void; close: () => Promise<void> }

const answerTheFileBody = (body: FileBody, file: NodeJS.ReadableStream, response: ServerResponse): Promise<void> =>
    new Promise((answered) => {
        if (body === 'stall after its first byte') {
            file.once('data', (chunk: Buffer) => {
                response.write(chunk.subarray(0, 1))
                setTimeout(answered, 100)
            })
            file.resume()
            return
        }
        const chunks: Buffer[] = []
        file.on('data', (chunk: Buffer) => chunks.push(chunk))
        file.on('end', () => {
            const bytes = Buffer.concat(chunks)
            bytes[bytes.length - 1] ^= 0xff
            response.end(bytes, answered)
        })
    })

const bucketProxyThat = async (fault: BucketFault): Promise<BucketProxy> => {
    let bodyAnswered: () => void = () => undefined
    const answered = new Promise<void>((resolve) => (bodyAnswered = resolve))
    const server = createServer((request, response) => {
        if (fault === 'stall every copy' && request.headers['x-amz-copy-source']) {
            request.resume()
            return
        }
        const upstream = httpRequest(
            new URL(request.url!, config.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT),
            { method: request.method, headers: request.headers },
            (answer) => {
                response.writeHead(answer.statusCode!, answer.headers)
                if (fault !== 'stall every copy' && request.method === 'GET' && answer.statusCode === 200) {
                    void answerTheFileBody(fault, answer, response).then(bodyAnswered)
                    return
                }
                answer.pipe(response)
            }
        )
        request.pipe(upstream)
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const cut = (): void => {
        server.close()
        server.closeAllConnections()
    }
    return {
        endpoint: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
        bodyAnswered: answered,
        cut,
        close: () => new Promise((resolve) => (cut(), server.close(() => resolve()))),
    }
}

const withTheClockAt = async <T>(at: Date, act: () => Promise<T>): Promise<T> => {
    jest.useFakeTimers({
        now: at,
        doNotFake: [
            'hrtime',
            'nextTick',
            'performance',
            'queueMicrotask',
            'setImmediate',
            'clearImmediate',
            'setInterval',
            'clearInterval',
            'setTimeout',
            'clearTimeout',
        ],
    })
    try {
        return await act()
    } finally {
        jest.useRealTimers()
    }
}

describe('S3AttachmentStore', () => {
    let store: S3AttachmentStore

    const storeAt = (now: Date, signer: S3Client = store.s3, timeoutMs = 10000): S3AttachmentStore =>
        new S3AttachmentStore(
            store.s3,
            signer,
            { bucket: BUCKET, prefix: config.CDP_EMAIL_ATTACHMENTS_S3_PREFIX, timeoutMs },
            () => now
        )

    const signerWith = (credentials: Parameters<typeof credentialsThatOutliveUploadUrls>[0]): S3Client =>
        new S3Client({
            region: config.CDP_EMAIL_ATTACHMENTS_S3_REGION,
            endpoint: config.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT,
            forcePathStyle: true,
            credentials: credentialsThatOutliveUploadUrls(credentials),
        })

    const realCredentials = {
        accessKeyId: config.CDP_EMAIL_ATTACHMENTS_S3_ACCESS_KEY_ID,
        secretAccessKey: config.CDP_EMAIL_ATTACHMENTS_S3_SECRET_ACCESS_KEY,
    }

    const askFor = async (at: S3AttachmentStore, teamId: number, f: TestFile): Promise<UploadSlot> => {
        const [slot] = await at.prepareUploads(teamId, [{ sha256: f.sha256, size: f.bytes.length }])
        return slot
    }

    const expiryOf = async (teamId: number, f: TestFile): Promise<Date> => {
        const slot = await askFor(store, teamId, f)
        if (slot.status !== 'present') {
            throw new Error(`expected ${f.sha256} to be present, got ${slot.status}`)
        }
        return slot.expiresAt
    }

    const uploaded = async (teamId: number, f: TestFile): Promise<Date> => {
        expect((await put(await askFor(store, teamId, f), f.bytes)).status).toBe(200)
        return await expiryOf(teamId, f)
    }

    const uploadedAt = async (teamId: number, f: TestFile): Promise<Date> =>
        new Date((await uploaded(teamId, f)).getTime() - ATTACHMENT_LIFETIME_MS)

    const untilAKeepWouldMoveTheExpiry = async (expiresAt: Date): Promise<void> => {
        const storedAt = expiresAt.getTime() - ATTACHMENT_LIFETIME_MS
        while (Date.now() <= storedAt + BUCKET_CLOCK_PRECISION_MS) {
            await new Promise((resolve) => setTimeout(resolve, storedAt + BUCKET_CLOCK_PRECISION_MS + 1 - Date.now()))
        }
    }

    const storedUnderItsHashWithAnotherFilesChecksum = async (teamId: number, f: TestFile): Promise<void> => {
        const other = file()
        await store.s3.send(
            new PutObjectCommand({
                Bucket: BUCKET,
                Key: `${config.CDP_EMAIL_ATTACHMENTS_S3_PREFIX}/team/${teamId}/${f.sha256}`,
                Body: other.bytes,
                ChecksumSHA256: Buffer.from(other.sha256, 'hex').toString('base64'),
            })
        )
    }

    beforeAll(async () => {
        store = buildAttachmentStore(config)!
        await store.s3.send(new CreateBucketCommand({ Bucket: BUCKET })).catch((error: Error) => {
            if (error.name !== 'BucketAlreadyOwnedByYou' && error.name !== 'BucketAlreadyExists') {
                throw error
            }
        })
    })

    afterAll(() => store.s3.destroy())

    describe('prepareUploads', () => {
        it('answers upload with a URL for the next 15 minutes, then present until 37 days after the upload', async () => {
            const f = file()
            const asked = Date.now()

            const slot = await askFor(store, 1, f)

            expect(slot).toMatchObject({ sha256: f.sha256, status: 'upload', method: 'PUT' })
            const { urlExpiresAt } = slot as UploadUrl
            expect(urlExpiresAt.getTime()).toBeGreaterThanOrEqual(asked + 15 * MINUTE_MS)
            expect(urlExpiresAt.getTime()).toBeLessThanOrEqual(Date.now() + 15 * MINUTE_MS)

            const putAt = Date.now()
            expect((await put(slot, f.bytes)).status).toBe(200)
            const putDone = Date.now()

            const again = (await askFor(store, 1, f)) as Present
            expect(again).toEqual({ sha256: f.sha256, status: 'present', expiresAt: expect.any(Date) })
            expect(again.expiresAt.getTime()).toBeGreaterThanOrEqual(
                putAt - BUCKET_CLOCK_PRECISION_MS + ATTACHMENT_LIFETIME_MS
            )
            expect(again.expiresAt.getTime()).toBeLessThanOrEqual(putDone + ATTACHMENT_LIFETIME_MS)
        })

        it.each([
            ['takes the file 14 minutes after it was signed', 14, 200],
            ['refuses the file 16 minutes after it was signed', 16, 403],
        ])('gives a URL that %s', async (_, minutesAgo, status) => {
            const f = file()
            const slot = await withTheClockAt(minutesFromNow(-minutesAgo), () => askFor(store, 1, f))

            expect((await put(slot, f.bytes)).status).toBe(status)
        })

        it('lets the bucket refuse a body that differs from the declared hash, and stores nothing', async () => {
            const f = file()
            const slot = await askFor(store, 1, f)

            const response = await put(slot, Buffer.from(f.bytes).fill(0x41, f.bytes.length - 1))

            expect(response.status).toBeGreaterThanOrEqual(400)
            await expect(
                store.acceptForSend(1, [{ sha256: f.sha256, filename: 'a.pdf' }], new Date())
            ).resolves.toEqual({ refusal: 'attachment_not_uploaded', sha256: f.sha256 })
        })

        it.each([
            [
                'would expire within a day of the URL',
                async (f: TestFile) => new Date((await uploaded(1, f)).getTime() - DAY_MS),
                1,
            ],
            ['belongs to another team', async (f: TestFile) => (await uploaded(2, f), new Date()), 1],
            [
                'is stored under its hash with another checksum, as send refuses it',
                async (f: TestFile) => (await storedUnderItsHashWithAnotherFilesChecksum(1, f), new Date()),
                1,
            ],
        ])('answers upload for a file that %s', async (_, storedAndAskedAt, askingTeam) => {
            const f = file()
            const askedAt = await storedAndAskedAt(f)

            const slot = await askFor(storeAt(askedAt), askingTeam, f)

            expect(slot.status).toBe('upload')
        })

        it('refuses a hash that could name another key', async () => {
            await expect(store.prepareUploads(1, [{ sha256: '../2/' + 'a'.repeat(59), size: 1 }])).rejects.toThrow(
                'not a SHA-256'
            )
        })

        it('gives URLs that work when the cached credentials expire too soon and a forced refresh renews them', async () => {
            const chainThatForgetsRefreshes = ({ forceRefresh }: { forceRefresh?: boolean } = {}): Promise<{
                accessKeyId: string
                secretAccessKey: string
                expiration: Date
            }> =>
                Promise.resolve(
                    forceRefresh
                        ? { ...realCredentials, expiration: minutesFromNow(60) }
                        : { accessKeyId: 'revoked', secretAccessKey: 'revoked', expiration: minutesFromNow(10) }
                )
            const [pdf, logo] = [file(), file()]

            const slots = await storeAt(new Date(), signerWith(chainThatForgetsRefreshes)).prepareUploads(1, [
                { sha256: pdf.sha256, size: pdf.bytes.length },
                { sha256: logo.sha256, size: logo.bytes.length },
            ])

            expect((await put(slots[0], pdf.bytes)).status).toBe(200)
            expect((await put(slots[1], logo.bytes)).status).toBe(200)
        })

        it.each([
            [
                'expire before the URL even after a forced refresh',
                () => Promise.resolve({ ...realCredentials, expiration: minutesFromNow(10) }),
            ],
            ['never arrive', () => new Promise<never>(() => {})],
        ])('throws unavailable instead of signing when the credentials %s', async (_, credentials) => {
            const signing = askFor(storeAt(new Date(), signerWith(credentials), 200), 1, file())

            await expect(signing).rejects.toThrow(AttachmentStoreUnavailableError)
        })
    })

    describe('acceptForSend', () => {
        it('accepts files present under the team, with their stored sizes', async () => {
            const [pdf, logo] = [file(), file()]
            await uploaded(1, pdf)
            await uploaded(1, logo)

            const answer = await store.acceptForSend(
                1,
                [
                    { sha256: pdf.sha256, filename: 'invoice.pdf', contentType: 'application/pdf' },
                    { sha256: logo.sha256, filename: 'logo.png', contentId: 'logo' },
                ],
                new Date(Date.now() + 7 * DAY_MS)
            )

            expect(answer).toEqual({
                files: [
                    {
                        sha256: pdf.sha256,
                        filename: 'invoice.pdf',
                        contentType: 'application/pdf',
                        sizeBytes: pdf.bytes.length,
                    },
                    { sha256: logo.sha256, filename: 'logo.png', contentId: 'logo', sizeBytes: logo.bytes.length },
                ],
            })
        })

        it('refuses a send naming the first file missing under the team, and keeps none of the others longer', async () => {
            const [stored, othersTeam, never] = [file(), file(), file()]
            const expiresAt = await uploaded(1, stored)
            await uploaded(2, othersTeam)
            await untilAKeepWouldMoveTheExpiry(expiresAt)
            const storedAt = expiresAt.getTime() - ATTACHMENT_LIFETIME_MS

            const answer = await storeAt(new Date(storedAt + 2 * DAY_MS)).acceptForSend(
                1,
                [
                    { sha256: stored.sha256, filename: 'a.pdf' },
                    { sha256: othersTeam.sha256, filename: 'b.pdf' },
                    { sha256: never.sha256, filename: 'c.pdf' },
                ],
                new Date(storedAt + 38 * DAY_MS)
            )

            expect(answer).toEqual({ refusal: 'attachment_not_uploaded', sha256: othersTeam.sha256 })
            expect(await expiryOf(1, stored)).toEqual(expiresAt)
        })

        it('throws unavailable when the bucket cannot be reached', async () => {
            const down = buildAttachmentStore({ ...config, CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT: 'http://127.0.0.1:9' })!

            await expect(
                down.acceptForSend(1, [{ sha256: file().sha256, filename: 'a.pdf' }], new Date())
            ).rejects.toThrow(AttachmentStoreUnavailableError)
        })
    })

    describe('expiry through acceptForSend', () => {
        const use = (at: S3AttachmentStore, sha256: string, needsUntil: Date): Promise<unknown> =>
            at.acceptForSend(1, [{ sha256, filename: 'a.pdf' }], needsUntil)

        it('keeps a file through the latest time a use can need it, past its expiry at upload', async () => {
            const f = file()
            const expiresAt = await uploaded(1, f)
            await untilAKeepWouldMoveTheExpiry(expiresAt)
            const now = new Date()
            const needsUntil = new Date(now.getTime() + ATTACHMENT_LIFETIME_MS - BUCKET_CLOCK_PRECISION_MS)
            expect(expiresAt.getTime()).toBeLessThan(needsUntil.getTime())

            await use(storeAt(now), f.sha256, needsUntil)

            expect((await expiryOf(1, f)).getTime()).toBeGreaterThanOrEqual(needsUntil.getTime())
        })

        it.each([
            [
                'the use needs it no longer than it lives',
                (expiresAt: Date) => ({ now: new Date(Date.now() + DAY_MS), needsUntil: expiresAt }),
            ],
            [
                'the use comes within a second of the upload and needs it until the expiry prepareUploads answered',
                (expiresAt: Date) => ({
                    now: new Date(expiresAt.getTime() - ATTACHMENT_LIFETIME_MS + BUCKET_CLOCK_PRECISION_MS / 2),
                    needsUntil: expiresAt,
                }),
            ],
        ])('leaves the expiry alone when %s', async (_, timing) => {
            const f = file()
            const expiresAt = await uploaded(1, f)
            await untilAKeepWouldMoveTheExpiry(expiresAt)
            const { now, needsUntil } = timing(expiresAt)

            await use(storeAt(now), f.sha256, needsUntil)

            expect(await expiryOf(1, f)).toEqual(expiresAt)
        })

        it('refuses a use that needs a file past what a keep now can reach, and leaves its expiry alone', async () => {
            const f = file()
            const expiresAt = await uploaded(1, f)
            await untilAKeepWouldMoveTheExpiry(expiresAt)
            const now = new Date()

            await expect(
                use(storeAt(now), f.sha256, new Date(now.getTime() + ATTACHMENT_LIFETIME_MS + 1000))
            ).rejects.toThrow(RangeError)
            expect(await expiryOf(1, f)).toEqual(expiresAt)
        })

        it.each([
            [
                'the bucket stalls the copy',
                async (): Promise<{ s3: S3Client; close: () => Promise<void> }> => {
                    const bucket = await bucketProxyThat('stall every copy')
                    const viaBucket = buildAttachmentStore({
                        ...config,
                        CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT: bucket.endpoint,
                    })!
                    return {
                        s3: viaBucket.s3,
                        close: async () => {
                            viaBucket.s3.destroy()
                            await bucket.close()
                        },
                    }
                },
            ],
            [
                'the credentials stop answering once the copy starts',
                (): Promise<{ s3: S3Client; close: () => Promise<void> }> => {
                    let copying = false
                    const askedOnEveryRequest = Object.assign(
                        () => (copying ? new Promise<never>(() => {}) : Promise.resolve(realCredentials)),
                        { memoized: true }
                    )
                    const s3 = new S3Client({
                        region: config.CDP_EMAIL_ATTACHMENTS_S3_REGION,
                        endpoint: config.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT,
                        forcePathStyle: true,
                        credentials: askedOnEveryRequest,
                    })
                    s3.middlewareStack.add(
                        (next, context) => (args) => {
                            copying ||= context.commandName === 'CopyObjectCommand'
                            return next(args)
                        },
                        { step: 'initialize' }
                    )
                    return Promise.resolve({ s3, close: () => Promise.resolve(s3.destroy()) })
                },
            ],
        ])('throws unavailable when %s on the keep a use needs', async (_, stalling) => {
            const f = file()
            const storedAt = await uploadedAt(1, f)
            const { s3, close } = await stalling()
            const aDayLater = new S3AttachmentStore(
                s3,
                s3,
                { bucket: BUCKET, prefix: config.CDP_EMAIL_ATTACHMENTS_S3_PREFIX, timeoutMs: 200 },
                () => new Date(storedAt.getTime() + DAY_MS)
            )
            try {
                await expect(
                    use(aDayLater, f.sha256, new Date(storedAt.getTime() + ATTACHMENT_LIFETIME_MS + 1000))
                ).rejects.toThrow(AttachmentStoreUnavailableError)
            } finally {
                await close()
            }
        })

        it('keeps the file whole when two uses keep it at once', async () => {
            const f = file()
            const storedAt = (await uploadedAt(1, f)).getTime()
            const later = storeAt(new Date(storedAt + 2 * DAY_MS))
            const needsUntil = new Date(storedAt + 38 * DAY_MS)

            await Promise.all([use(later, f.sha256, needsUntil), use(later, f.sha256, needsUntil)])

            const [loaded] = await store.load(
                1,
                [{ sha256: f.sha256, filename: 'a.pdf', sizeBytes: f.bytes.length }],
                AbortSignal.timeout(10000)
            )
            expect(loaded.bytes).toEqual(new Uint8Array(f.bytes))
        })
    })

    describe('load', () => {
        it('returns the bytes of every file in order', async () => {
            const [pdf, logo] = [file(), file()]
            await uploaded(1, pdf)
            await uploaded(1, logo)
            const files = [
                { sha256: pdf.sha256, filename: 'invoice.pdf', sizeBytes: pdf.bytes.length },
                { sha256: logo.sha256, filename: 'logo.png', contentId: 'logo', sizeBytes: logo.bytes.length },
            ]

            const loaded = await store.load(1, files, AbortSignal.timeout(10000))

            expect(loaded).toEqual([
                { file: files[0], bytes: new Uint8Array(pdf.bytes) },
                { file: files[1], bytes: new Uint8Array(logo.bytes) },
            ])
        })

        it.each([
            ["another team's file", 2, (): AbortSignal => AbortSignal.timeout(10000), AttachmentMissingError],
            ['an aborted load', 1, (): AbortSignal => AbortSignal.abort(), AttachmentStoreUnavailableError],
        ])('throws for %s', async (_, ownerTeam, signal, error) => {
            const f = file()
            await uploaded(ownerTeam, f)

            await expect(
                store.load(1, [{ sha256: f.sha256, filename: 'a.pdf', sizeBytes: f.bytes.length }], signal())
            ).rejects.toThrow(error)
        })

        it.each([
            [
                'the caller aborts while the file body stalls',
                'stall after its first byte',
                (_: BucketProxy, caller: AbortController) => caller.abort(),
            ],
            [
                'the connection is cut while the file body stalls',
                'stall after its first byte',
                (bucket: BucketProxy) => bucket.cut(),
            ],
            ['the file body arrives with a changed byte', 'change its last byte', () => undefined],
        ] as const)('throws unavailable at once when %s', async (_, body, interrupt) => {
            const f = file()
            await uploaded(1, f)
            const bucket = await bucketProxyThat(body)
            const viaBucket = buildAttachmentStore({ ...config, CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT: bucket.endpoint })!
            const caller = new AbortController()
            try {
                const loading = viaBucket.load(
                    1,
                    [{ sha256: f.sha256, filename: 'a.pdf', sizeBytes: f.bytes.length }],
                    caller.signal
                )
                await bucket.bodyAnswered
                interrupt(bucket, caller)

                await expect(settledWithin(3000, loading)).rejects.toThrow(AttachmentStoreUnavailableError)
            } finally {
                viaBucket.s3.destroy()
                await bucket.close()
            }
        })
    })

    describe('when the bucket client never gets its credentials', () => {
        const sha256 = file().sha256

        it.each([
            ['prepareUploads', (at: S3AttachmentStore) => at.prepareUploads(1, [{ sha256, size: 10 }])],
            [
                'acceptForSend',
                (at: S3AttachmentStore) => at.acceptForSend(1, [{ sha256, filename: 'a.pdf' }], new Date()),
            ],
            [
                'load',
                (at: S3AttachmentStore) =>
                    at.load(1, [{ sha256, filename: 'a.pdf', sizeBytes: 10 }], AbortSignal.timeout(200)),
            ],
        ])('%s throws unavailable once its time is up', async (_, use) => {
            const stalled = new S3Client({
                region: config.CDP_EMAIL_ATTACHMENTS_S3_REGION,
                endpoint: config.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT,
                forcePathStyle: true,
                credentials: () => new Promise<never>(() => {}),
            })
            const at = new S3AttachmentStore(stalled, stalled, {
                bucket: BUCKET,
                prefix: config.CDP_EMAIL_ATTACHMENTS_S3_PREFIX,
                timeoutMs: 200,
            })

            await expect(use(at)).rejects.toThrow(AttachmentStoreUnavailableError)
        })
    })
})
