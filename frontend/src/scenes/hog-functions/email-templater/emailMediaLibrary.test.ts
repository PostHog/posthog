import type { Editor } from 'react-email-editor'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { registerEmailMediaLibrary } from './emailMediaLibrary'

jest.mock('posthog-js')

type Handler = (...args: any[]) => Promise<void>

function registerOnFakeEditor(): Record<string, Handler> {
    const handlers: Record<string, Handler> = {}
    const editor = {
        registerProvider: (type: string, handler: Handler) => (handlers[`provider:${type}`] = handler),
        registerCallback: (type: string, handler: Handler) => (handlers[type] = handler),
    } as unknown as Editor
    registerEmailMediaLibrary(editor, '1')
    return handlers
}

const MEDIA = {
    id: 'media-1',
    name: 'logo.png',
    purpose: 'email',
    content_type: 'image/png',
    size_bytes: 1024,
    width: null,
    height: null,
    url: 'http://localhost/uploaded_media/media-1',
    created_at: '2026-10-01T00:00:00Z',
}

describe('registerEmailMediaLibrary', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('lists a page of the email library in the shape the Uploads tab expects', async () => {
        const requestedParams: URLSearchParams[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/uploaded_media/': ({ request }) => {
                    requestedParams.push(new URL(request.url).searchParams)
                    return [200, { count: 41, next: 'http://localhost/next', previous: null, results: [MEDIA] }]
                },
            },
        })
        const done = jest.fn()

        await registerOnFakeEditor()['provider:userUploads']({ page: 3, searchText: ' logo ' }, done)

        expect(Object.fromEntries(requestedParams[0])).toEqual({
            purpose: 'email',
            limit: '20',
            offset: '40',
            search: 'logo',
        })
        expect(done).toHaveBeenCalledWith(
            [
                {
                    id: 'media-1',
                    location: 'http://localhost/uploaded_media/media-1',
                    width: 0,
                    height: 0,
                    contentType: 'image/png',
                    size: 1024,
                    source: 'user',
                },
            ],
            { hasMore: true, page: 3, perPage: 20, total: 41 }
        )
    })

    it.each([
        [
            'shows the reason the backend rejected the file',
            [400, { detail: 'Uploaded media must be less than 4MB' }],
            'Uploaded media must be less than 4MB',
        ],
        ['falls back to a generic message without one', [500, {}], "Couldn't upload this image. Try again."],
    ])('upload failure %s', async (_name, response, expectedError) => {
        useMocks({ post: { '/api/projects/:team_id/uploaded_media/': () => response } })
        const done = jest.fn()

        await registerOnFakeEditor()['image']({ attachments: [new File(['x'], 'big.png')] }, done)

        expect(done).toHaveBeenLastCalledWith({ error: expectedError })
    })

    describe('images over the upload limit', () => {
        const OVER_LIMIT_BYTES = 4 * 1024 * 1024 + 1
        const overLimitFile = (name: string, type: string): File =>
            new File([new Uint8Array(OVER_LIMIT_BYTES)], name, { type })
        const RESIZE_FAILED =
            "Couldn't resize this image automatically, and it's over the 4 MB limit. Use a smaller image and try again."

        function mockImageElement(size: { width: number; height: number } | 'unreadable'): void {
            URL.createObjectURL = jest.fn(() => 'blob:test')
            URL.revokeObjectURL = jest.fn()
            ;(globalThis as any).Image = class {
                onload = (): void => {}
                onerror = (): void => {}
                naturalWidth = size === 'unreadable' ? 0 : size.width
                naturalHeight = size === 'unreadable' ? 0 : size.height
                set src(_url: string) {
                    if (size === 'unreadable') {
                        this.onerror()
                    } else {
                        this.onload()
                    }
                }
            }
        }

        function mockBrowserImageApis(alpha: number, encodedSizes: number[]): jest.Mock {
            mockImageElement({ width: 3000, height: 1500 })
            ;(globalThis as any).createImageBitmap = jest.fn(async () => ({
                width: 3000,
                height: 1500,
                close: jest.fn(),
            }))
            jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
                drawImage: jest.fn(),
                getImageData: () => ({ data: new Uint8ClampedArray([0, 0, 0, alpha]) }),
            } as any)
            const toBlob = jest.fn()
            encodedSizes.forEach((size) =>
                toBlob.mockImplementationOnce((callback: BlobCallback, type: string) =>
                    callback(new Blob([new Uint8Array(size)], { type }))
                )
            )
            HTMLCanvasElement.prototype.toBlob = toBlob
            return toBlob
        }

        function useUploadCapture(): { name: string; type: string; size: number }[] {
            const uploads: { name: string; type: string; size: number }[] = []
            useMocks({
                post: {
                    '/api/projects/:team_id/uploaded_media/': async ({ request }) => {
                        const image = (await request.formData()).get('image') as File
                        uploads.push({ name: image.name, type: image.type, size: image.size })
                        return [201, { id: 'media-1', image_location: 'http://localhost/m', name: image.name }]
                    },
                },
            })
            return uploads
        }

        const originalImage = globalThis.Image

        afterEach(() => {
            jest.restoreAllMocks()
            globalThis.Image = originalImage
            delete (globalThis as any).createImageBitmap
        })

        it.each([
            ['keeps transparency as a PNG', 0, 'logo.png', 'image/png', 'logo.png', 'image/png'],
            ['uses a JPEG for an opaque PNG', 255, 'photo.png', 'image/png', 'photo.jpg', 'image/jpeg'],
        ])('%s', async (_name, alpha, inputName, inputType, outputName, outputType) => {
            const toBlob = mockBrowserImageApis(alpha, [OVER_LIMIT_BYTES, 1024])
            const uploads = useUploadCapture()
            const done = jest.fn()

            await registerOnFakeEditor()['image']({ attachments: [overLimitFile(inputName, inputType)] }, done)

            expect(toBlob).toHaveBeenCalledTimes(2)
            expect(uploads).toEqual([{ name: outputName, type: outputType, size: 1024 }])
            expect(done).toHaveBeenLastCalledWith(expect.objectContaining({ progress: 100 }))
        })

        it.each([
            ['a GIF, which would lose its animation', 'animated.gif', 'image/gif', { width: 800, height: 600 }],
            ['an image the browser cannot read', 'broken.png', 'image/png', 'unreadable' as const],
            ['an image too large to decode safely', 'huge.png', 'image/png', { width: 12000, height: 12000 }],
        ])('explains the failure without decoding or uploading %s', async (_name, fileName, type, size) => {
            mockImageElement(size)
            const decode = jest.fn()
            ;(globalThis as any).createImageBitmap = decode
            const uploads = useUploadCapture()
            const done = jest.fn()

            await registerOnFakeEditor()['image']({ attachments: [overLimitFile(fileName, type)] }, done)

            expect(decode).not.toHaveBeenCalled()
            expect(uploads).toEqual([])
            expect(done).toHaveBeenLastCalledWith({ error: RESIZE_FAILED })
        })
    })

    it.each([
        ['removed now', 204, true],
        ['already removed', 404, true],
        ['failed to remove', 500, false],
    ])('reports removal as finished only when the image is out of the library: %s', async (_name, status, finished) => {
        useMocks({ delete: { '/api/projects/:team_id/uploaded_media/:id/': () => [status] } })
        const done = jest.fn()

        await registerOnFakeEditor()['image:removed']({ id: 'media-1' }, done)

        expect(done).toHaveBeenCalledTimes(finished ? 1 : 0)
    })
})
