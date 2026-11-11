import { toBlob } from 'html-to-image'

import { BLANK_IMAGE, captureElementImage } from './captureElementImage'

jest.mock('html-to-image', () => ({
    toBlob: jest.fn(() => Promise.resolve(new Blob(['png'], { type: 'image/png' }))),
}))

describe('captureElementImage', () => {
    it('leaves CSS custom properties out of the copied style properties', async () => {
        document.documentElement.style.setProperty('--a-design-token', 'red')

        await captureElementImage(document.createElement('div'))

        const { includeStyleProperties } = (toBlob as jest.Mock).mock.calls[0][1]
        expect(includeStyleProperties).not.toBeUndefined()
        expect(includeStyleProperties.filter((name: string) => name.startsWith('--'))).toEqual([])
    })

    it('keys images by query string and degrades broken assets to a placeholder', async () => {
        await captureElementImage(document.createElement('div'))

        expect(toBlob).toHaveBeenCalledWith(
            expect.anything(),
            expect.objectContaining({ includeQueryParams: true, imagePlaceholder: BLANK_IMAGE })
        )
    })

    it('bounds the resource fetches so a stalled asset cannot hang the capture', async () => {
        jest.useFakeTimers()
        try {
            await captureElementImage(document.createElement('div'))

            const { fetchRequestInit } = (toBlob as jest.Mock).mock.calls[0][1]
            expect(fetchRequestInit.signal.aborted).toBe(false)

            await jest.advanceTimersByTimeAsync(15000)
            expect(fetchRequestInit.signal.aborted).toBe(true)
        } finally {
            jest.useRealTimers()
        }
    })
})
