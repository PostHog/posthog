import type {
    ImageFetchOptions,
    ImageFetchResult,
} from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/image-fetcher'

import { SharedImageFetcher } from './shared-image-fetcher'

const IMAGE_URL = 'https://example.com/a.png'
const OK: ImageFetchResult = {
    outcome: 'ok',
    redirects: 0,
    currentUrl: IMAGE_URL,
    bytes: Buffer.from('png'),
    contentType: 'image/png',
}
const options = (tdmrepReservation: boolean) => ({ tdmrepReservation }) as ImageFetchOptions

describe('SharedImageFetcher', () => {
    it.each([
        ['one after the other', false],
        ['at the same time', true],
    ])('fetches again for a job whose TDM reservation differs, %s', async (_name, concurrent) => {
        const inner = { fetch: jest.fn((_url: string, _options: ImageFetchOptions) => Promise.resolve(OK)) }
        const fetcher = new SharedImageFetcher(inner)

        if (concurrent) {
            await Promise.all([fetcher.fetch(IMAGE_URL, options(false)), fetcher.fetch(IMAGE_URL, options(true))])
        } else {
            await fetcher.fetch(IMAGE_URL, options(false))
            await fetcher.fetch(IMAGE_URL, options(true))
        }
        await fetcher.fetch(IMAGE_URL, options(true))

        expect(inner.fetch.mock.calls.map(([, used]) => used.tdmrepReservation)).toEqual([false, true])
    })
})
