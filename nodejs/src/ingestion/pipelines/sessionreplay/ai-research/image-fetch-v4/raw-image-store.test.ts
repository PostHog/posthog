import { CopyObjectCommand, PutObjectCommand, S3ServiceException } from '@aws-sdk/client-s3'
import { createDecipheriv } from 'node:crypto'

import { parseJSON } from '~/common/utils/json-parse'
import type { TeamMonthKey } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-month-keys'

import type { FetchCandidate } from './collected-urls-record'
import type { ImageFetchResult } from './image-fetcher'
import { RawImageStore } from './raw-image-store'

const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from('png body')])
const REF = 'imageurl:v4:7:2026-10:abcdefghijklmnopqrstuv'
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
const fetched = (bytes = PNG): ImageFetchResult => ({
    outcome: 'ok',
    redirects: 0,
    currentUrl: IMAGE_URL,
    status: 200,
    bytes,
    contentType: 'image/png',
})

describe('RawImageStore', () => {
    it('stores the image sealed under its team month key, over any earlier object of its reference', async () => {
        const { sink, puts } = store(STORED)
        await sink.publishImage(candidate(), fetched())

        expect(puts).toHaveLength(1)
        expect(puts[0]).toBeInstanceOf(PutObjectCommand)
        const { Bucket, Key, IfNoneMatch, Body, ContentType } = (puts[0] as PutObjectCommand).input
        expect([Bucket, Key, IfNoneMatch]).toEqual([
            'images-v4',
            'images/url/month=2026-10/7/abcdefghijklmnopqrstuv',
            undefined,
        ])
        const { aad, body } = open(Body as Buffer)
        expect(body).toEqual(PNG)
        expect(aad).toEqual({
            v: 4,
            context: { teamId: 7, keyMonth: '2026-10', kind: 'image-url', codec: 'none', ref: REF },
        })

        // The refresh copies the object onto itself, which resets the creation time the lifecycle counts from.
        await expect(sink.refreshImage(candidate())).resolves.toBe(true)
        expect(puts[1]).toBeInstanceOf(CopyObjectCommand)
        expect((puts[1] as CopyObjectCommand).input).toEqual({
            Bucket,
            Key,
            CopySource: 'images-v4/images/url/month%3D2026-10/7/abcdefghijklmnopqrstuv',
            MetadataDirective: 'REPLACE',
            ContentType,
        })
    })

    it('resolves to false when it refreshes a reference that has no object', async () => {
        const { sink, puts } = store(STORED, NOT_FOUND)
        await expect(sink.refreshImage(candidate())).resolves.toBe(false)
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
    ] as const)('resolves without a new object for %s', async (_name, key, job, result) => {
        const { sink, puts } = store(key)
        await expect(sink.publishImage(job, result)).resolves.toBeUndefined()
        expect(puts).toHaveLength(0)
    })

    it('holds a further image back while the write limit is full, so a slow S3 does not pile up images in memory', async () => {
        let finishWrite!: () => void
        const s3 = {
            send: jest.fn(() => new Promise((resolve) => (finishWrite = () => resolve({})))),
        }
        const keyReads = jest.fn(() => Promise.resolve(STORED))
        const sink = new RawImageStore({ get: keyReads }, s3 as any, 'images-v4', 1)

        const first = sink.publishImage(candidate(), fetched())
        const second = sink.publishImage(candidate(), fetched())
        await new Promise((resolve) => setImmediate(resolve))
        expect([s3.send.mock.calls.length, keyReads.mock.calls.length]).toEqual([1, 1])

        finishWrite()
        await first
        await new Promise((resolve) => setImmediate(resolve))
        finishWrite()
        await second
        expect(s3.send).toHaveBeenCalledTimes(2)
    })
})
