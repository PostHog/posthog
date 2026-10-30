import type { ImageFetchOptions, ImageFetchResult } from './image-fetcher'
import { SharedImageFetcher } from './shared-image-fetcher'

const IMAGE_URL = 'https://example.com/a.png'
const OK: ImageFetchResult = {
    outcome: 'ok',
    redirects: 0,
    currentUrl: IMAGE_URL,
    bytes: Buffer.from('png'),
    contentType: 'image/png',
}
const options = (tdmrepReservation: boolean, asset: ImageFetchOptions['asset'] = 'image') =>
    ({ tdmrepReservation, asset }) as ImageFetchOptions

describe('SharedImageFetcher', () => {
    it.each([
        ['TDM reservation', 'one after the other', options(false), options(true)],
        ['TDM reservation', 'at the same time', options(false), options(true)],
        ['asset', 'one after the other', options(false), options(false, 'font')],
        ['asset', 'at the same time', options(false), options(false, 'font')],
    ])('fetches again for a job whose %s differs, %s', async (_field, timing, first, second) => {
        const inner = { fetch: jest.fn((_url: string, _options: ImageFetchOptions) => Promise.resolve(OK)) }
        const fetcher = new SharedImageFetcher(inner)

        if (timing === 'at the same time') {
            await Promise.all([fetcher.fetch(IMAGE_URL, first), fetcher.fetch(IMAGE_URL, second)])
        } else {
            await fetcher.fetch(IMAGE_URL, first)
            await fetcher.fetch(IMAGE_URL, second)
        }
        await fetcher.fetch(IMAGE_URL, second)

        expect(inner.fetch.mock.calls.map(([, used]) => used)).toEqual([first, second])
    })

    it.each([
        ['more entries than its cap', Buffer.from('png'), 64 * 1024 * 1024, 2],
        ['empty images whose URLs and headers outgrow its size', Buffer.alloc(0), 3_000, 100],
    ])('evicts the oldest image when it holds %s', async (_name, bytes, maxBytes, maxEntries) => {
        const inner = {
            fetch: jest.fn((url: string, _options: ImageFetchOptions) =>
                Promise.resolve({ ...OK, currentUrl: url, bytes })
            ),
        }
        const fetcher = new SharedImageFetcher(inner, maxBytes, 60_000, maxEntries)
        const urls = ['a', 'b', 'c', 'a'].map((name) => `https://example.com/${name}.png`)

        for (const url of urls) {
            await fetcher.fetch(url, options(false))
        }

        expect(inner.fetch.mock.calls.map(([url]) => url)).toEqual(urls)
    })
})
