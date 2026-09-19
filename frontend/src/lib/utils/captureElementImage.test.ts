import { toBlob } from 'html-to-image'

import { captureElementImage } from './captureElementImage'

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

    it('lets a broken page asset degrade the image instead of failing the capture', async () => {
        await captureElementImage(document.createElement('div'))

        const { imagePlaceholder, onImageErrorHandler } = (toBlob as jest.Mock).mock.calls[0][1]
        expect(imagePlaceholder).toMatch(/^data:image\//)
        expect(() => onImageErrorHandler(new Event('error'))).not.toThrow()
    })

    it('bounds the resource fetches so a stalled asset cannot hang the capture', async () => {
        jest.useFakeTimers()
        try {
            await captureElementImage(document.createElement('div'))

            const { fetchRequestInit } = (toBlob as jest.Mock).mock.calls[0][1]
            expect(fetchRequestInit.signal.aborted).toBe(false)

            await jest.advanceTimersByTimeAsync(60000)
            expect(fetchRequestInit.signal.aborted).toBe(true)
        } finally {
            jest.useRealTimers()
        }
    })
})
