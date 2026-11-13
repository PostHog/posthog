import { CopyObjectCommand, GetObjectCommand, PutObjectCommand, S3ServiceException } from '@aws-sdk/client-s3'
import { createDecipheriv } from 'node:crypto'

import type { ProducerMessage } from '~/common/kafka/producer'
import { parseJSON } from '~/common/utils/json-parse'
import type { TeamMonthKey } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-month-keys'

import type { FetchCandidate } from './collected-urls-record'
import type { UrlCrawlHistoryItem } from './crawl-history'
import type { ImageFetchResult } from './image-fetcher'
import { ImagePacker } from './image-packer'
import { RawImageStore } from './raw-image-store'

const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from('png body')])
const WOFF2 = Buffer.from('wOF2 body')
const REF = 'imageurl:v4:7:2026-10:abcdefghijklmnopqrstuv'
const FONT_REF = 'fonturl:v4:7:2026-10:abcdefghijklmnopqrstuv'
const PUBLIC_FONT_URL = 'https://fonts.gstatic.com/s/roboto/v30/KFOmCnqEu92Fr1Mu4mxK.woff2'
const PUBLIC_FONT_REF = 'fonturl:v4:public:I6bjVBXgjPcaYLPITibNM4'
const KEY = Buffer.alloc(32, 9)
const STORED: TeamMonthKey = { status: 'ok', key: KEY }

function open(frame: Buffer): { aad: any; body: Buffer } {
    const length = frame.readUInt16BE(6)
    const aad = frame.subarray(8, 8 + length)
    const nonce = frame.subarray(8 + length, 20 + length)
    const sealed = frame.subarray(20 + length)
    const decipher = createDecipheriv('aes-256-gcm', KEY, nonce, { authTagLength: 16 })
    decipher.setAAD(aad)
    decipher.setAuthTag(sealed.subarray(sealed.length - 16))
    const body = Buffer.concat([decipher.update(sealed.subarray(0, sealed.length - 16)), decipher.final()])
    return { aad: parseJSON(aad.toString()), body }
}

const NOT_FOUND = new S3ServiceException({ name: 'NoSuchKey', $fault: 'client', $metadata: { httpStatusCode: 404 } })

function store(key: TeamMonthKey, s3Error?: Error) {
    const puts: (PutObjectCommand | CopyObjectCommand)[] = []
    const s3 = {
        send: jest.fn((command: PutObjectCommand | CopyObjectCommand) => {
            puts.push(command)
            return s3Error ? Promise.reject(s3Error) : Promise.resolve({})
        }),
    }
    return { sink: new RawImageStore({ get: () => Promise.resolve(key) }, s3 as any, 'images-v4', 10), puts }
}

const IMAGE_URL = 'https://images.example.com/logo.png'

const candidate = (ref = REF): FetchCandidate => ({
    originalRef: ref,
    currentUrl: IMAGE_URL,
    host: 'images.example.com',
    origin: 'https://images.example.com',
    registrableDomain: 'example.com',
    remainingHops: 10,
    notBeforeMs: 0,
    firstSeenAtMs: 0,
    fetchCount: 0,
    republishCount: 0,
    lastRepublishReason: null,
})
const fetched = (bytes = PNG, contentType = 'image/png'): ImageFetchResult => ({
    outcome: 'ok',
    redirects: 0,
    currentUrl: IMAGE_URL,
    status: 200,
    bytes,
    contentType,
})

// Noon UTC on 2026-10-14. Rows for that day reach the index in time until 23:00.
const NOON_MS = Date.parse('2026-10-14T12:00:00Z')
const PNG_2 = Buffer.concat([PNG, Buffer.from(' two')])
const REF_2 = 'imageurl:v4:7:2026-10:bcdefghijklmnopqrstuvw'

type S3Command = PutObjectCommand | CopyObjectCommand | GetObjectCommand

/** An in-memory bucket that answers puts, copies and ranged gets. */
function packingStore(options: { maxPackImages?: number; packer?: boolean; failPuts?: boolean } = {}) {
    const objects = new Map<string, Buffer>()
    const commands: S3Command[] = []
    const s3 = {
        send: jest.fn((command: S3Command) => {
            commands.push(command)
            if (command instanceof PutObjectCommand) {
                if (options.failPuts) {
                    return Promise.reject(new Error('SlowDown'))
                }
                objects.set(command.input.Key!, command.input.Body as Buffer)
                return Promise.resolve({})
            }
            if (command instanceof GetObjectCommand) {
                const object = objects.get(command.input.Key!)
                if (!object) {
                    return Promise.reject(NOT_FOUND)
                }
                const [start, end] = command.input.Range!.slice('bytes='.length).split('-').map(Number)
                const range = object.subarray(start, end + 1)
                return Promise.resolve({ Body: { transformToByteArray: () => Promise.resolve(range) } })
            }
            return Promise.resolve({})
        }),
    }
    const rows: ProducerMessage[] = []
    const packer =
        options.packer === false
            ? undefined
            : new ImagePacker(s3 as any, 'images-v4', {
                  index: { produce: (message) => Promise.resolve(void rows.push(message)) },
                  indexTopic: 'ai_research_v4_index',
                  lingerMs: 60_000,
                  maxPackBytes: 1024 * 1024,
                  maxPackImages: options.maxPackImages ?? 1,
              })
    const sink = new RawImageStore({ get: () => Promise.resolve(STORED) }, s3 as any, 'images-v4', 10, packer)
    const puts = (): string[] =>
        commands.filter((command) => command instanceof PutObjectCommand).map((command) => command.input.Key!)
    return { sink, objects, commands, puts, rows }
}

/** `null` for a job with no write days. */
const job = (ref = REF, writeDays: string[] | null = ['2026-10-14']): FetchCandidate => ({
    ...candidate(ref),
    ...(writeDays ? { writeDays } : {}),
})

function packedHistory(ref: string, pack: NonNullable<UrlCrawlHistoryItem['pack']>): UrlCrawlHistoryItem {
    return {
        kind: 'url',
        key: ref,
        nextFetchAtMs: NOON_MS + 1_000_000,
        storageExpiresAtMs: NOON_MS + 1_000_000,
        outcome: 'ok',
        storedAtMs: pack.storedAtMs,
        pack,
    }
}

describe('RawImageStore', () => {
    it.each([
        ['image', REF, fetched(), PNG, 'images/url', 'image-url'],
        ['font', FONT_REF, fetched(WOFF2, 'font/woff2'), WOFF2, 'fonts/url', 'font-url'],
    ])(
        'stores the %s sealed under its team month key, over any earlier object of its reference',
        async (_asset, ref, result, bytes, prefix, kind) => {
            const { sink, puts } = store(STORED)
            await sink.publishImage(candidate(ref), result)

            expect(puts).toHaveLength(1)
            expect(puts[0]).toBeInstanceOf(PutObjectCommand)
            const { Bucket, Key, IfNoneMatch, Body, ContentType } = (puts[0] as PutObjectCommand).input
            expect([Bucket, Key, IfNoneMatch]).toEqual([
                'images-v4',
                `${prefix}/month=2026-10/7/abcdefghijklmnopqrstuv`,
                undefined,
            ])
            const { aad, body } = open(Body as Buffer)
            expect(body).toEqual(bytes)
            expect(aad).toEqual({
                v: 4,
                context: { teamId: 7, keyMonth: '2026-10', kind, codec: 'none', ref },
            })

            // The refresh copies the object onto itself, which resets the creation time the lifecycle counts from.
            await expect(sink.refreshImage(candidate(ref), undefined)).resolves.toEqual({})
            expect(puts[1]).toBeInstanceOf(CopyObjectCommand)
            expect((puts[1] as CopyObjectCommand).input).toEqual({
                Bucket,
                Key,
                CopySource: `images-v4/${prefix}/month%3D2026-10/7/abcdefghijklmnopqrstuv`,
                MetadataDirective: 'REPLACE',
                ContentType,
            })
        }
    )

    it('stores a public font once and unsealed, with no team key, and refreshes that one object', async () => {
        const keyReads = jest.fn(() => Promise.resolve(STORED))
        const puts: (PutObjectCommand | CopyObjectCommand)[] = []
        const s3 = { send: jest.fn((command: PutObjectCommand | CopyObjectCommand) => puts.push(command)) }
        const sink = new RawImageStore({ get: keyReads }, s3 as any, 'images-v4', 10)
        const job = { ...candidate(PUBLIC_FONT_REF), currentUrl: PUBLIC_FONT_URL }

        await sink.publishImage(job, fetched(WOFF2, 'font/woff2'))
        await expect(sink.refreshImage(job, undefined)).resolves.toEqual({})

        expect(keyReads).not.toHaveBeenCalled()
        expect(puts.map((command) => [command.constructor.name, command.input.Key])).toEqual([
            ['PutObjectCommand', 'fonts/url/public/I6bjVBXgjPcaYLPITibNM4'],
            ['CopyObjectCommand', 'fonts/url/public/I6bjVBXgjPcaYLPITibNM4'],
        ])
        expect((puts[0] as PutObjectCommand).input.Body).toEqual(WOFF2)
    })

    it('resolves to null when it refreshes a reference that has no object', async () => {
        const { sink, puts } = store(STORED, NOT_FOUND)
        await expect(sink.refreshImage(candidate(), undefined)).resolves.toBeNull()
        expect(puts).toHaveLength(1)
    })

    it.each([
        ['a tombstoned team month', { status: 'deleted' }, candidate(), fetched()],
        ['a team month without a key row', { status: 'missing' }, candidate(), fetched()],
        ['a body that is not the image it claims to be', STORED, candidate(), fetched(Buffer.from('<html>'))],
        [
            'a reference from another dataset',
            STORED,
            candidate('imageurl:v3:7:2026-10:abcdefghijklmnopqrstuv'),
            fetched(),
        ],
        [
            'a public font reference whose job ended on another URL, such as a redirect target',
            STORED,
            candidate(PUBLIC_FONT_REF),
            fetched(WOFF2, 'font/woff2'),
        ],
    ] as const)('resolves without a new object for %s', async (_name, key, job, result) => {
        const { sink, puts } = store(key)
        await expect(sink.publishImage(job, result)).resolves.toEqual({})
        expect(puts).toHaveLength(0)
    })

    it('holds a further image back while the write limit is full, so a slow S3 does not pile up images in memory', async () => {
        const finishWrites: (() => void)[] = []
        let writeStarted!: () => void
        let started = new Promise<void>((resolve) => (writeStarted = resolve))
        const s3 = {
            send: jest.fn(
                () =>
                    new Promise((resolve) => {
                        finishWrites.push(() => resolve({}))
                        writeStarted()
                    })
            ),
        }
        const keyReads = jest.fn(() => Promise.resolve(STORED))
        const sink = new RawImageStore({ get: keyReads }, s3 as any, 'images-v4', 1)

        const first = sink.publishImage(candidate(), fetched())
        const second = sink.publishImage(candidate(), fetched())
        await started
        await new Promise((resolve) => setImmediate(resolve))
        expect([s3.send.mock.calls.length, keyReads.mock.calls.length]).toEqual([1, 1])

        started = new Promise<void>((resolve) => (writeStarted = resolve))
        finishWrites[0]()
        await first
        await started
        finishWrites[1]()
        await second
        expect(s3.send).toHaveBeenCalledTimes(2)
    })
    describe('with a packer', () => {
        beforeEach(() => jest.useFakeTimers({ now: NOON_MS, doNotFake: ['setImmediate', 'nextTick'] }))
        afterEach(() => jest.useRealTimers())

        it('packs a team images into one object and sends each image a row for its write day, where readers find them', async () => {
            const { sink, objects, puts, rows } = packingStore({ maxPackImages: 2 })

            const [first, second] = await Promise.all([
                sink.publishImage(job(REF), fetched()),
                sink.publishImage(job(REF_2), fetched(PNG_2)),
            ])

            expect(puts()).toEqual([expect.stringMatching(/^images\/url\/packs\/dt=2026-10-14\/7\/\d+-[0-9a-f]{16}$/)])
            const pack = objects.get(puts()[0])!
            for (const [stored, bytes] of [
                [first, PNG],
                [second, PNG_2],
            ] as const) {
                const { key, byteStart, byteEnd } = stored.pack!
                expect(key).toBe(puts()[0])
                expect(open(pack.subarray(byteStart, byteEnd + 1)).body).toEqual(bytes)
                expect(stored.pack).toMatchObject({ mime: 'image/png', byteSize: bytes.length, storedAtMs: NOON_MS })
            }
            expect(
                rows.map(({ topic, key, headers, value }) => [
                    topic,
                    (key as Buffer).toString(),
                    headers,
                    parseJSON(value!.toString()),
                ])
            ).toEqual([
                [
                    'ai_research_v4_index',
                    REF,
                    { 'ml-index': 'images', 'ml-write-day': '2026-10-14' },
                    {
                        team_id: 7,
                        key_month: '2026-10',
                        image_ref: REF,
                        pack_s3_key: puts()[0],
                        byte_start: first.pack!.byteStart,
                        byte_end: first.pack!.byteEnd,
                        mime: 'image/png',
                        byte_size: PNG.length,
                    },
                ],
                [
                    'ai_research_v4_index',
                    REF_2,
                    { 'ml-index': 'images', 'ml-write-day': '2026-10-14' },
                    expect.objectContaining({ image_ref: REF_2, byte_start: second.pack!.byteStart }),
                ],
            ])
        })

        it.each([
            ['a job from a recorder that sends no write days', NOON_MS, job(REF, null), fetched(), true],
            [
                'a write day that ends within the hour',
                Date.parse('2026-10-14T23:30:00Z'),
                job(REF, ['2026-10-14']),
                fetched(),
                true,
            ],
            ['a write day that has ended', NOON_MS, job(REF, ['2026-10-13', '2026-10-14']), fetched(), true],
            ['a font', NOON_MS, job(FONT_REF), fetched(WOFF2, 'font/woff2'), true],
            ['a lane with packing off', NOON_MS, job(REF), fetched(), false],
        ])('stores the one object of its reference for %s', async (_name, nowMs, candidateJob, result, packer) => {
            jest.setSystemTime(nowMs)
            const { sink, puts, rows } = packingStore({ packer })

            await expect(sink.publishImage(candidateJob, result)).resolves.toEqual({})

            expect(puts()).toEqual([expect.stringMatching(/^(images|fonts)\/url\/month=2026-10\/7\//)])
            expect(rows).toEqual([])
        })

        it('rejects every image of a pack whose write fails, so each one is fetched again', async () => {
            const { sink, rows } = packingStore({ maxPackImages: 2, failPuts: true })

            const results = await Promise.allSettled([
                sink.publishImage(job(REF), fetched()),
                sink.publishImage(job(REF_2), fetched(PNG_2)),
            ])

            expect(results.map((result) => result.status)).toEqual(['rejected', 'rejected'])
            expect(rows).toEqual([])
        })

        it('refreshes a packed copy by writing its frame into a new pack, which a copy onto itself cannot do', async () => {
            const { sink, objects, puts } = packingStore()
            const stored = await sink.publishImage(job(REF), fetched())
            jest.setSystemTime(NOON_MS + 1)

            const refreshed = await sink.refreshImage(job(REF), packedHistory(REF, stored.pack!))

            expect(puts()).toHaveLength(2)
            expect(refreshed!.pack!.key).toBe(puts()[1])
            expect(refreshed!.pack!.storedAtMs).toBe(NOON_MS + 1)
            const { byteStart, byteEnd } = refreshed!.pack!
            expect(open(objects.get(puts()[1])!.subarray(byteStart, byteEnd + 1)).body).toEqual(PNG)
        })

        it('resolves to null when it refreshes a packed copy whose pack is gone', async () => {
            const { sink } = packingStore()
            const gone = {
                key: 'images/url/packs/dt=2026-07-01/7/1-00000000000000aa',
                byteStart: 0,
                byteEnd: 9,
                mime: 'image/png',
                byteSize: 4,
                storedAtMs: NOON_MS - 1,
            }

            await expect(sink.refreshImage(job(REF), packedHistory(REF, gone))).resolves.toBeNull()
        })

        it('sends only rows for a packed copy that needs no refresh, and unpacks it when the rows would be late', async () => {
            const { sink, objects, puts, rows } = packingStore()
            const stored = await sink.publishImage(job(REF), fetched())
            rows.length = 0

            await sink.indexStoredImage(job(REF, ['2026-10-14']), packedHistory(REF, stored.pack!))
            expect(puts()).toHaveLength(1)
            expect(rows.map((row) => row.headers)).toEqual([{ 'ml-index': 'images', 'ml-write-day': '2026-10-14' }])

            await sink.indexStoredImage(job(REF, null), packedHistory(REF, stored.pack!))
            expect(puts()[1]).toBe('images/url/month=2026-10/7/abcdefghijklmnopqrstuv')
            expect(open(objects.get(puts()[1])!).body).toEqual(PNG)
            expect(rows).toHaveLength(1)
        })
    })
})
