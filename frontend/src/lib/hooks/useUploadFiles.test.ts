import api from 'lib/api'

import { uploadFile } from './useUploadFiles'

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
