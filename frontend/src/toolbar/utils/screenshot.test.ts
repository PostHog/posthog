import { toBlob } from 'html-to-image'

import { captureElementScreenshot } from '~/toolbar/utils/screenshot'

jest.mock('html-to-image', () => ({
    toBlob: jest.fn(),
}))

const mockToBlob = toBlob as jest.Mock

describe('captureElementScreenshot', () => {
    beforeEach(() => mockToBlob.mockReset())

    it('rethrows a raw DOM Event rejection as a real Error with the element and original type', async () => {
        // html-to-image rejects with an Event, not an Error, when a page resource fails to load.
        // A bare Event reaches error tracking with no message and no stack.
        mockToBlob.mockRejectedValueOnce(new Event('error'))
        const element = document.createElement('img')
        element.id = 'logo'

        await expect(captureElementScreenshot(element)).rejects.toThrow(
            'Failed to capture screenshot of img#logo (threw Event)'
        )
    })

    it('throws a real Error when toBlob resolves to null', async () => {
        mockToBlob.mockResolvedValueOnce(null)

        await expect(captureElementScreenshot(document.documentElement)).rejects.toThrow(
            'Failed to capture screenshot of html'
        )
    })

    it('returns the blob on success', async () => {
        const blob = new Blob(['x'], { type: 'image/jpeg' })
        mockToBlob.mockResolvedValueOnce(blob)

        await expect(captureElementScreenshot(document.documentElement)).resolves.toBe(blob)
    })
})
