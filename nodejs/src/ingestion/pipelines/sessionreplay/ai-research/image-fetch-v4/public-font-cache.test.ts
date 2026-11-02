import { GetObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3'
import { gzipSync } from 'zlib'

import type { ImageFetchOptions, ImageFetchResult } from './image-fetcher'
import { PublicFontCache, publicFontKey } from './public-font-cache'

const GOOGLE_FONT_URL = 'https://fonts.gstatic.com/s/lobster/v30/neILzCirqoswsqX9zoKmMw.woff2'
const WOFF2 = Buffer.concat([Buffer.from('wOF2'), Buffer.alloc(60, 1)])
const FONT: ImageFetchResult = {
    outcome: 'ok',
    redirects: 0,
    currentUrl: GOOGLE_FONT_URL,
    status: 200,
    bytes: WOFF2,
    contentType: 'font/woff2',
}
const options = (asset: ImageFetchOptions['asset'], tdmrepReservation = false) =>
    ({ asset, tdmrepReservation }) as ImageFetchOptions

function fakeS3(readError?: Error) {
    const objects = new Map<string, { body: Buffer; contentType?: string }>()
    const send = jest.fn((command: GetObjectCommand | PutObjectCommand) => {
        const key = command.input.Key!
        if (command instanceof PutObjectCommand) {
            objects.set(key, { body: command.input.Body as Buffer, contentType: command.input.ContentType })
            return Promise.resolve({})
        }
        const object = objects.get(key)
        if (readError) {
            return Promise.reject(readError)
        }
        if (!object) {
            return Promise.reject(Object.assign(new Error('The specified key does not exist.'), { name: 'NoSuchKey' }))
        }
        return Promise.resolve({
            Body: { transformToByteArray: () => Promise.resolve(new Uint8Array(object.body)) },
            ContentType: object.contentType,
        })
    })
    return { send, objects }
}

describe('PublicFontCache', () => {
    it.each([
        ['as sent', FONT],
        ['sent compressed', { ...FONT, bytes: gzipSync(WOFF2), contentEncoding: 'gzip' }],
    ])('asks Google once for a font file %s, and gives every later job the font', async (_name, sent) => {
        const inner = { fetch: jest.fn(() => Promise.resolve(sent)) }
        const s3 = fakeS3()
        const cache = new PublicFontCache(inner, s3, 'images-v4')

        expect(await cache.fetch(GOOGLE_FONT_URL, options('font'))).toBe(sent)
        const later = await cache.fetch(GOOGLE_FONT_URL, options('font'))

        expect(inner.fetch).toHaveBeenCalledTimes(1)
        expect(later).toEqual({ ...FONT, contentEncoding: undefined })
        expect([...s3.objects.keys()]).toEqual([publicFontKey(GOOGLE_FONT_URL)])
    })

    it.each<[string, string, ImageFetchOptions, ImageFetchResult, Error | undefined]>([
        [
            'an image',
            'https://fonts.gstatic.com/s/a.png',
            options('image'),
            { ...FONT, contentType: 'image/png' },
            undefined,
        ],
        ['a font from a site', 'https://cdn.example.com/a.woff2', options('font'), FONT, undefined],
        ['a job under a TDM reservation', GOOGLE_FONT_URL, options('font', true), FONT, undefined],
        ['a redirected font', GOOGLE_FONT_URL, options('font'), { ...FONT, redirects: 1 }, undefined],
        [
            'a body that is not a font',
            GOOGLE_FONT_URL,
            options('font'),
            { ...FONT, bytes: Buffer.from('<html>') },
            undefined,
        ],
        ['a copy it cannot read', GOOGLE_FONT_URL, options('font'), FONT, new Error('Access Denied')],
    ])('asks the host for every job of %s', async (_name, url, used, sent, readError) => {
        const inner = { fetch: jest.fn(() => Promise.resolve(sent)) }
        const cache = new PublicFontCache(inner, fakeS3(readError), 'images-v4')

        expect(await cache.fetch(url, used)).toBe(sent)
        expect(await cache.fetch(url, used)).toBe(sent)

        expect(inner.fetch).toHaveBeenCalledTimes(2)
    })
})
