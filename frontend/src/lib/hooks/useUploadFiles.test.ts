import api from 'lib/api'

import { lazyImageBlobReducer, uploadFile } from './useUploadFiles'

const allowedMimeTypes = ['image/png']
const maxSizeBytes = 4

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        media: {
            upload: jest.fn(),
        },
    },
}))

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { captureException: jest.fn() },
}))

const reduceToBlob = jest.fn()
jest.mock('image-blob-reduce', () => ({
    __esModule: true,
    default: () => ({ toBlob: reduceToBlob }),
}))

describe('useUploadFiles', () => {
    describe('uploadFile', () => {
        beforeEach(() => {
            jest.clearAllMocks()
        })

        it.each([['video/mp4', 'File is not an image']])('rejects %s before uploading', async (type, message) => {
            await expect(
                uploadFile(new File(['file'], 'file', { type }), {
                    allowedMimeTypes,
                    maxSizeBytes,
                })
            ).rejects.toThrow(message)
            expect(api.media.upload).not.toHaveBeenCalled()
        })

        it('rejects an image format excluded by the caller', async () => {
            await expect(
                uploadFile(new File(['file'], 'file.svg', { type: 'image/svg+xml' }), {
                    allowedMimeTypes,
                    maxSizeBytes,
                })
            ).rejects.toThrow('This image format is not supported')
            expect(api.media.upload).not.toHaveBeenCalled()
        })

        it('rejects an image larger than the configured upload limit before decoding', async () => {
            const file = new File([new Uint8Array(maxSizeBytes + 1)], 'image.png', { type: 'image/png' })

            await expect(
                uploadFile(file, {
                    allowedMimeTypes,
                    maxSizeBytes,
                })
            ).rejects.toThrow('Image exceeds the maximum file size')
            expect(api.media.upload).not.toHaveBeenCalled()
        })
    })

    describe('lazyImageBlobReducer', () => {
        const canvasSizes: [number, number][] = []
        const convertToBlobMock = jest.fn()

        // Stands in for a browser that decodes the image and resizes it on an OffscreenCanvas.
        const givenResizeEnvironment = (bitmap: { width: number; height: number }): void => {
            Reflect.set(globalThis, 'createImageBitmap', jest.fn().mockResolvedValue({ ...bitmap, close: jest.fn() }))
            Reflect.set(
                globalThis,
                'OffscreenCanvas',
                class {
                    constructor(width: number, height: number) {
                        canvasSizes.push([width, height])
                    }
                    getContext = (): unknown => ({ drawImage: jest.fn() })
                    convertToBlob = convertToBlobMock
                }
            )
        }

        beforeEach(() => {
            canvasSizes.length = 0
            convertToBlobMock.mockReset()
            reduceToBlob.mockRejectedValue(new Error('canvas is unavailable'))
        })

        afterEach(() => {
            Reflect.deleteProperty(globalThis, 'createImageBitmap')
            Reflect.deleteProperty(globalThis, 'OffscreenCanvas')
        })

        it('rejects an image the browser cannot decode, so it is never uploaded', async () => {
            Reflect.set(globalThis, 'OffscreenCanvas', class {})
            Reflect.set(
                globalThis,
                'createImageBitmap',
                jest.fn().mockRejectedValue(new Error('Cannot decode the data in the argument to createImageBitmap'))
            )

            await expect(lazyImageBlobReducer(new Blob(['not an image']))).rejects.toThrow(
                "This image can't be read, try a different file"
            )
        })

        it('keeps the original image when the browser cannot resize at all', async () => {
            const blob = new Blob(['image bytes'])

            await expect(lazyImageBlobReducer(blob)).resolves.toBe(blob)
        })

        it('keeps the original image when compression fails after the image decoded', async () => {
            givenResizeEnvironment({ width: 1, height: 4001 })
            convertToBlobMock.mockRejectedValue(new Error('The size of "OffscreenCanvas" is zero'))
            const blob = new Blob(['image bytes'])

            await expect(lazyImageBlobReducer(blob)).resolves.toBe(blob)
        })

        it('resizes a very thin image on a canvas at least one pixel wide', async () => {
            givenResizeEnvironment({ width: 1, height: 4001 })
            const resized = new Blob(['resized bytes'])
            convertToBlobMock.mockResolvedValue(resized)

            await expect(lazyImageBlobReducer(new Blob(['image bytes']))).resolves.toBe(resized)
            expect(canvasSizes).toEqual([[1, 2000]])
        })
    })
})
