import { toBlob, toSvg } from 'html-to-image'

import { BLANK_IMAGE, captureElementImage, captureElementSvg } from './captureElementImage'

jest.mock('html-to-image', () => ({
    toBlob: jest.fn(() => Promise.resolve(new Blob(['png'], { type: 'image/png' }))),
    toSvg: jest.fn(() => Promise.resolve('data:image/svg+xml;charset=utf-8,')),
}))

describe('captureElementImage', () => {
    const captures = [
        { name: 'captureElementImage', capture: captureElementImage, renderer: toBlob as jest.Mock },
        { name: 'captureElementSvg', capture: captureElementSvg, renderer: toSvg as jest.Mock },
    ]

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it.each(captures)(
        '$name leaves CSS custom properties out of the copied style properties',
        async ({ capture, renderer }) => {
            document.documentElement.style.setProperty('--a-design-token', 'red')

            await capture(document.createElement('div'))

            const { includeStyleProperties } = renderer.mock.calls[0][1]
            expect(includeStyleProperties).not.toBeUndefined()
            expect(includeStyleProperties.filter((name: string) => name.startsWith('--'))).toEqual([])
        }
    )

    it.each(captures)(
        '$name keys images by query string and degrades broken assets to a placeholder',
        async ({ capture, renderer }) => {
            await capture(document.createElement('div'))

            expect(renderer).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({
                    includeQueryParams: true,
                    imagePlaceholder: BLANK_IMAGE,
                    onImageErrorHandler: expect.any(Function),
                })
            )
        }
    )

    it.each(captures)(
        '$name bounds the resource fetches so a stalled asset cannot hang the capture',
        async ({ capture, renderer }) => {
            jest.useFakeTimers()
            try {
                await capture(document.createElement('div'))

                const { fetchRequestInit } = renderer.mock.calls[0][1]
                expect(fetchRequestInit.signal.aborted).toBe(false)

                await jest.advanceTimersByTimeAsync(15000)
                expect(fetchRequestInit.signal.aborted).toBe(true)
            } finally {
                jest.useRealTimers()
            }
        }
    )
})
