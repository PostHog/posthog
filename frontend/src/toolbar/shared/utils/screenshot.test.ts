import { toBlob } from 'html-to-image'

import { captureElementScreenshot } from '~/toolbar/shared/utils/screenshot'

jest.mock('html-to-image', () => ({
    toBlob: jest.fn(),
}))

const mockToBlob = toBlob as jest.Mock

describe('captureElementScreenshot', () => {
    beforeEach(() => mockToBlob.mockReset())

    it.each([
        // html-to-image rejects with an Event, not an Error, when a page resource fails to load.
        // A bare Event reaches error tracking with no message and no stack.
        { thrown: new Event('error'), type: 'Event' },
        // Its own errors can quote a page URL, which must not reach error tracking.
        {
            thrown: new SyntaxError("'/icons.svg?token=secret#logo' is not a valid selector."),
            type: 'SyntaxError',
        },
    ])('rethrows a $type rejection as an Error that names only the element and the type', async ({ thrown, type }) => {
        mockToBlob.mockRejectedValueOnce(thrown)
        const element = document.createElement('img')
        element.id = 'logo'

        const error = await captureElementScreenshot(element).catch((caught: Error) => caught)

        expect(error).toBeInstanceOf(Error)
        expect((error as Error).message).toEqual(`Failed to capture screenshot of img#logo (threw ${type})`)
        expect((error as Error).stack).not.toContain('secret')
    })

    it('throws a real Error when toBlob resolves to null', async () => {
        mockToBlob.mockResolvedValueOnce(null)

        await expect(captureElementScreenshot(document.documentElement)).rejects.toThrow(
            'Rendering the element to an image produced no data'
        )
    })

    it('returns a JPEG on a white background so transparent areas do not turn black', async () => {
        const blob = new Blob(['x'], { type: 'image/jpeg' })
        mockToBlob.mockResolvedValueOnce(blob)

        await expect(captureElementScreenshot(document.documentElement)).resolves.toBe(blob)
        expect(mockToBlob).toHaveBeenCalledWith(
            document.documentElement,
            expect.objectContaining({ type: 'image/jpeg', backgroundColor: '#ffffff' })
        )
    })
})
