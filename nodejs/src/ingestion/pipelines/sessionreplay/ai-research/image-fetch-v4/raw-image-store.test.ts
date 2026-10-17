import { PutObjectCommand, S3ServiceException } from '@aws-sdk/client-s3'
import { createDecipheriv } from 'node:crypto'

import { parseJSON } from '~/common/utils/json-parse'
import type { TeamDayKey } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-day-keys'
import type { FetchCandidate } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/collected-urls-record'
import type { ImageFetchResult } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/image-fetcher'

import { RawImageStore } from './raw-image-store'

const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from('png body')])
const REF = 'imageurl:v4:7:2026-10-15:abcdefghijklmnopqrstuv'
const KEY = Buffer.alloc(32, 9)
const STORED: TeamDayKey = { status: 'ok', key: KEY }

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

function store(key: TeamDayKey, putError?: Error) {
    const puts: PutObjectCommand[] = []
    const s3 = {
        send: jest.fn((command: PutObjectCommand) => {
            puts.push(command)
            return putError ? Promise.reject(putError) : Promise.resolve({})
        }),
    }
    return { sink: new RawImageStore({ get: () => Promise.resolve(key) }, s3 as any, 'images-v4', 10), puts }
}

const candidate = (ref = REF) => ({ originalRef: ref }) as FetchCandidate
const fetched = (bytes = PNG, contentType = 'image/png') => ({ outcome: 'ok', bytes, contentType }) as ImageFetchResult

describe('RawImageStore', () => {
    it('stores the image sealed under its team day key, at a key derived from its reference', async () => {
        const { sink, puts } = store(STORED)
        await sink.publishImage(candidate(), fetched())

        expect(puts).toHaveLength(1)
        const { Bucket, Key, IfNoneMatch, Body } = puts[0].input
        expect([Bucket, Key, IfNoneMatch]).toEqual([
            'images-v4',
            'images/url/dt=2026-10-15/7/abcdefghijklmnopqrstuv',
            '*',
        ])
        const { aad, body } = open(Body as Buffer)
        expect(body).toEqual(PNG)
        expect(aad).toEqual({
            v: 4,
            context: { teamId: 7, keyDay: '2026-10-15', kind: 'image-url', codec: 'none', ref: REF },
        })
    })

    it.each([
        ['a tombstoned team day', { status: 'deleted' }, candidate(), fetched(), undefined],
        ['a team day without a key row', { status: 'missing' }, candidate(), fetched(), undefined],
        [
            'a body that is not the image it claims to be',
            STORED,
            candidate(),
            fetched(Buffer.from('<html>')),
            undefined,
        ],
        [
            'a reference from another dataset',
            STORED,
            candidate('imageurl:v3:7:2026-10:abcdefghijklmnopqrstuv'),
            fetched(),
            undefined,
        ],
        [
            'a reference stored before',
            STORED,
            candidate(),
            fetched(),
            new S3ServiceException({
                name: 'PreconditionFailed',
                $fault: 'client',
                $metadata: { httpStatusCode: 412 },
            }),
        ],
    ] as const)('resolves without a new object for %s', async (_name, key, job, result, putError) => {
        const { sink, puts } = store(key, putError)
        await expect(sink.publishImage(job, result)).resolves.toBeUndefined()
        expect(puts.length).toBe(putError ? 1 : 0)
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
