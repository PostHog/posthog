import { CopyObjectCommand, CreateBucketCommand, HeadObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { createHash, randomBytes } from 'node:crypto'

import { getDefaultCdpConfig } from '~/cdp/config'
import { FetchResponse, internalFetch } from '~/common/utils/request'

import {
    AttachmentMissingError,
    AttachmentStoreUnavailableError,
    S3AttachmentStore,
    UploadSlot,
    buildAttachmentStore,
    credentialsThatOutliveUploadUrls,
} from './attachment-store'

jest.setTimeout(30000)

const DAY_MS = 24 * 60 * 60 * 1000
const config = { ...getDefaultCdpConfig(), CDP_EMAIL_ATTACHMENTS_S3_PREFIX: `attachments-test/${Date.now()}` }
const BUCKET = config.CDP_EMAIL_ATTACHMENTS_S3_BUCKET

type TestFile = { bytes: Buffer; sha256: string }

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

describe('S3AttachmentStore', () => {
    let s3: S3Client
    let store: S3AttachmentStore

    const keyOf = (teamId: number, sha256: string): string =>
        `${config.CDP_EMAIL_ATTACHMENTS_S3_PREFIX}/team/${teamId}/${sha256}`

    const lastModified = async (teamId: number, sha256: string): Promise<Date> =>
        (await s3.send(new HeadObjectCommand({ Bucket: BUCKET, Key: keyOf(teamId, sha256) }))).LastModified!

    const upload = async (teamId: number, f: TestFile): Promise<void> => {
        const [slot] = await store.prepareUploads(teamId, [{ sha256: f.sha256, size: f.bytes.length }])
        expect((await put(slot, f.bytes)).status).toBe(200)
    }

    const storeAt = (now: Date, signer: S3Client = store.s3, timeoutMs = 10000): S3AttachmentStore =>
        new S3AttachmentStore(
            store.s3,
            signer,
            { bucket: BUCKET, prefix: config.CDP_EMAIL_ATTACHMENTS_S3_PREFIX, timeoutMs },
            () => now
        )

    const signerWith = (credentials: Parameters<typeof credentialsThatOutliveUploadUrls>[0]): S3Client =>
        new S3Client({
            region: 'us-east-1',
            endpoint: 'https://uploads.example.com',
            forcePathStyle: true,
            credentials: credentialsThatOutliveUploadUrls(credentials),
        })

    const expiringIn = (minutes: number): Date => new Date(Date.now() + minutes * 60 * 1000)

    const selfCopiesOf = (send: jest.SpyInstance, teamId: number, sha256: string): number =>
        send.mock.calls.filter(
            ([command]) => command instanceof CopyObjectCommand && command.input.Key === keyOf(teamId, sha256)
        ).length

    beforeAll(async () => {
        store = buildAttachmentStore(config)!
        s3 = new S3Client({
            region: config.CDP_EMAIL_ATTACHMENTS_S3_REGION,
            endpoint: config.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT,
            forcePathStyle: true,
            credentials: {
                accessKeyId: config.CDP_EMAIL_ATTACHMENTS_S3_ACCESS_KEY_ID,
                secretAccessKey: config.CDP_EMAIL_ATTACHMENTS_S3_SECRET_ACCESS_KEY,
            },
        })
        await s3.send(new CreateBucketCommand({ Bucket: BUCKET })).catch((error: Error) => {
            if (error.name !== 'BucketAlreadyOwnedByYou' && error.name !== 'BucketAlreadyExists') {
                throw error
            }
        })
    })

    afterEach(() => jest.restoreAllMocks())

    afterAll(() => s3.destroy())

    describe('prepareUploads', () => {
        it('signs a 15-minute PUT for a missing file, then answers present with its expiry once uploaded', async () => {
            const f = file()
            const before = Date.now()

            const [slot] = await store.prepareUploads(1, [{ sha256: f.sha256, size: f.bytes.length }])

            expect(slot).toMatchObject({
                sha256: f.sha256,
                status: 'upload',
                method: 'PUT',
                headers: {
                    'Content-Length': String(f.bytes.length),
                    'x-amz-checksum-sha256': createHash('sha256').update(f.bytes).digest('base64'),
                },
            })
            const { url, urlExpiresAt } = slot as Extract<UploadSlot, { status: 'upload' }>
            expect(new URL(url).searchParams.get('X-Amz-Expires')).toBe('900')
            expect(urlExpiresAt.getTime() - before).toBeGreaterThanOrEqual(15 * 60 * 1000)
            expect((await put(slot, f.bytes)).status).toBe(200)

            const [again] = await store.prepareUploads(1, [{ sha256: f.sha256, size: f.bytes.length }])
            const createdAt = await lastModified(1, f.sha256)
            expect(again).toEqual({
                sha256: f.sha256,
                status: 'present',
                expiresAt: new Date(createdAt.getTime() + 37 * DAY_MS),
            })
        })

        it('lets the bucket refuse a body that differs from the declared hash, and stores nothing', async () => {
            const f = file()
            const [slot] = await store.prepareUploads(1, [{ sha256: f.sha256, size: f.bytes.length }])

            const response = await put(slot, Buffer.from(f.bytes).fill(0x41, f.bytes.length - 1))

            expect(response.status).toBeGreaterThanOrEqual(400)
            await expect(
                store.acceptForSend(1, [{ sha256: f.sha256, filename: 'a.pdf' }], new Date())
            ).resolves.toEqual({ refusal: 'attachment_not_uploaded', sha256: f.sha256 })
        })

        it.each([
            ['would expire within a day of the URL', 1, 36 * DAY_MS],
            ['belongs to another team', 2, 0],
        ])('answers upload for a file that %s', async (_, askingTeam, clockOffsetMs) => {
            const f = file()
            await upload(1, f)
            const createdAt = await lastModified(1, f.sha256)

            const [slot] = await storeAt(new Date(createdAt.getTime() + clockOffsetMs)).prepareUploads(askingTeam, [
                { sha256: f.sha256, size: f.bytes.length },
            ])

            expect(slot.status).toBe('upload')
        })

        it('refuses a hash that could name another key', async () => {
            await expect(store.prepareUploads(1, [{ sha256: '../2/' + 'a'.repeat(59), size: 1 }])).rejects.toThrow(
                'not a SHA-256'
            )
        })

        it('signs with credentials that outlive the URL, keeping the ones a forced refresh returned', async () => {
            // Like the default provider chain: a forced refresh is answered but never cached.
            const defaultChain = jest.fn(({ forceRefresh }: { forceRefresh?: boolean } = {}) =>
                Promise.resolve(
                    forceRefresh
                        ? { accessKeyId: 'fresh', secretAccessKey: 'secret', expiration: expiringIn(60) }
                        : { accessKeyId: 'stale', secretAccessKey: 'secret', expiration: expiringIn(10) }
                )
            )

            const slots = await storeAt(new Date(), signerWith(defaultChain)).prepareUploads(1, [
                { sha256: file().sha256, size: 10 },
                { sha256: file().sha256, size: 10 },
            ])

            for (const slot of slots) {
                const url = new URL((slot as Extract<UploadSlot, { status: 'upload' }>).url)
                expect(url.host).toBe('uploads.example.com')
                expect(url.searchParams.get('X-Amz-Credential')).toMatch(/^fresh\//)
            }
        })

        it.each([
            [
                'expire before the URL even after a forced refresh',
                () => Promise.resolve({ accessKeyId: 'stale', secretAccessKey: 'secret', expiration: expiringIn(10) }),
            ],
            ['never arrive', () => new Promise<never>(() => {})],
        ])('throws unavailable instead of signing when the credentials %s', async (_, credentials) => {
            const signing = storeAt(new Date(), signerWith(credentials), 200).prepareUploads(1, [
                { sha256: file().sha256, size: 10 },
            ])

            await expect(signing).rejects.toThrow(AttachmentStoreUnavailableError)
        })
    })

    describe('acceptForSend', () => {
        it('accepts files present under the team, with their stored sizes', async () => {
            const [pdf, logo] = [file(), file()]
            await upload(1, pdf)
            await upload(1, logo)

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

        it('refuses a send naming the first file that is missing under the team', async () => {
            const [uploaded, othersTeam, never] = [file(), file(), file()]
            await upload(1, uploaded)
            await upload(2, othersTeam)

            const answer = await store.acceptForSend(
                1,
                [
                    { sha256: uploaded.sha256, filename: 'a.pdf' },
                    { sha256: othersTeam.sha256, filename: 'b.pdf' },
                    { sha256: never.sha256, filename: 'c.pdf' },
                ],
                new Date()
            )

            expect(answer).toEqual({ refusal: 'attachment_not_uploaded', sha256: othersTeam.sha256 })
        })

        it('throws unavailable when the bucket cannot be reached', async () => {
            const down = buildAttachmentStore({ ...config, CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT: 'http://127.0.0.1:9' })!

            await expect(
                down.acceptForSend(1, [{ sha256: file().sha256, filename: 'a.pdf' }], new Date())
            ).rejects.toThrow(AttachmentStoreUnavailableError)
        })
    })

    describe.each([
        [
            'acceptForSend',
            (at: S3AttachmentStore, sha256: string, needsUntil: Date): Promise<unknown> =>
                at.acceptForSend(1, [{ sha256, filename: 'a.pdf' }], needsUntil),
        ],
        [
            'extend',
            (at: S3AttachmentStore, sha256: string, needsUntil: Date): Promise<unknown> =>
                at.extend(1, [sha256], needsUntil),
        ],
    ])('expiry through %s', (_, use) => {
        it.each([
            ['copies a file onto itself when a use needs it past its expiry', 37 * DAY_MS + 1000, 1],
            ['leaves a file alone when it outlives the use', 37 * DAY_MS, 0],
        ])('%s', async (_, needsAfterCreationMs, copies) => {
            const f = file()
            await upload(1, f)
            const createdAt = await lastModified(1, f.sha256)
            const send = jest.spyOn(store.s3, 'send')

            await use(
                storeAt(new Date(createdAt.getTime() + DAY_MS)),
                f.sha256,
                new Date(createdAt.getTime() + needsAfterCreationMs)
            )

            expect(selfCopiesOf(send, 1, f.sha256)).toBe(copies)
        })

        it('throws unavailable when the copy a use needs does not settle in time', async () => {
            const f = file()
            await upload(1, f)
            const createdAt = await lastModified(1, f.sha256)
            const send = store.s3.send.bind(store.s3)
            jest.spyOn(store.s3, 'send').mockImplementation(((command: unknown, ...rest: unknown[]) =>
                command instanceof CopyObjectCommand
                    ? new Promise<never>(() => {})
                    : (send as (...args: unknown[]) => Promise<unknown>)(command, ...rest)) as typeof store.s3.send)

            await expect(
                use(
                    storeAt(new Date(createdAt.getTime() + DAY_MS), store.s3, 200),
                    f.sha256,
                    new Date(createdAt.getTime() + 37 * DAY_MS + 1000)
                )
            ).rejects.toThrow(AttachmentStoreUnavailableError)
        })

        it('keeps a fresh upload through the expiry that prepareUploads answered for it', async () => {
            const f = file()
            await upload(1, f)
            const [present] = await store.prepareUploads(1, [{ sha256: f.sha256, size: f.bytes.length }])
            const send = jest.spyOn(store.s3, 'send')

            await use(store, f.sha256, (present as Extract<UploadSlot, { status: 'present' }>).expiresAt)

            expect(selfCopiesOf(send, 1, f.sha256)).toBe(0)
        })

        it('refuses a use that needs a file past what a copy now can keep', async () => {
            const f = file()
            await upload(1, f)
            const now = new Date()
            const send = jest.spyOn(store.s3, 'send')

            await expect(use(storeAt(now), f.sha256, new Date(now.getTime() + 37 * DAY_MS + 1000))).rejects.toThrow(
                RangeError
            )
            expect(selfCopiesOf(send, 1, f.sha256)).toBe(0)
        })

        it('keeps the file whole when two uses copy it at once', async () => {
            const f = file()
            await upload(1, f)
            const createdAt = await lastModified(1, f.sha256)
            const later = storeAt(new Date(createdAt.getTime() + 2 * DAY_MS))
            const needsUntil = new Date(createdAt.getTime() + 38 * DAY_MS)

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
            await upload(1, pdf)
            await upload(1, logo)
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
            await upload(ownerTeam, f)

            await expect(
                store.load(1, [{ sha256: f.sha256, filename: 'a.pdf', sizeBytes: f.bytes.length }], signal())
            ).rejects.toThrow(error)
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
            ['extend', (at: S3AttachmentStore) => at.extend(1, [sha256], new Date())],
            [
                'load',
                (at: S3AttachmentStore) =>
                    at.load(1, [{ sha256, filename: 'a.pdf', sizeBytes: 10 }], AbortSignal.timeout(200)),
            ],
        ])('%s throws unavailable once its time is up', async (_, use) => {
            const stalled = new S3Client({
                region: 'us-east-1',
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
