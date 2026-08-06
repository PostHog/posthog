import { lazyImageBlobReducer, UnreadableImageError } from './useUploadFiles'

jest.mock('posthog-js', () => ({ captureException: jest.fn() }))

// image-blob-reduce is dynamically imported; force its reducer to fail so we always take the fallback path.
jest.mock('image-blob-reduce', () => ({
    default: () => ({
        toBlob: () => {
            throw new Error('canvas blocked')
        },
    }),
}))

describe('lazyImageBlobReducer', () => {
    const blob = new Blob(['not really an image'], { type: 'image/png' })

    afterEach(() => {
        delete (global as any).createImageBitmap
        delete (global as any).OffscreenCanvas
    })

    it('fails fast with UnreadableImageError when the browser cannot decode the image', async () => {
        // OffscreenCanvas present so we reach the decode attempt rather than the missing-API guard.
        ;(global as any).OffscreenCanvas = class {}
        ;(global as any).createImageBitmap = jest
            .fn()
            .mockRejectedValue(new DOMException('The source image could not be decoded.', 'InvalidStateError'))

        await expect(lazyImageBlobReducer(blob)).rejects.toBeInstanceOf(UnreadableImageError)
    })

    it('returns the original blob when no resize API is available', async () => {
        // No OffscreenCanvas/createImageBitmap: a possibly-valid image we just cannot resize, so let the server judge.
        await expect(lazyImageBlobReducer(blob)).resolves.toBe(blob)
    })
})
