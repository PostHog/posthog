import { BLANK_IMAGE } from 'lib/utils/captureElementImage'

import { captureResponsiveScreenshots } from '~/toolbar/utils/responsiveScreenshot'

jest.mock('~/toolbar/utils/screenshot', () => ({
    captureElementScreenshot: jest.fn(() => Promise.reject(new Error('capture failed'))),
}))
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    captureToolbarException: jest.fn(),
}))
jest.mock('~/toolbar/toolbarLogger', () => ({
    toolbarLogger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

const { captureElementScreenshot } = jest.requireMock('~/toolbar/utils/screenshot')
const { captureToolbarException } = jest.requireMock('~/toolbar/toolbarPosthogJS')
const { toolbarLogger } = jest.requireMock('~/toolbar/toolbarLogger')

describe('captureResponsiveScreenshots', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        ;(captureElementScreenshot as jest.Mock).mockImplementation(() => Promise.reject(new Error('capture failed')))
        ;(captureToolbarException as jest.Mock).mockClear()
        ;(toolbarLogger.warn as jest.Mock).mockClear()
    })
    afterEach(() => {
        jest.useRealTimers()
        document.body.innerHTML = ''
    })

    it('skips every failed width and resolves to an empty array instead of throwing', async () => {
        const onProgress = jest.fn()
        const promise = captureResponsiveScreenshots([320, 768, 1440], onProgress)
        await jest.runAllTimersAsync()

        await expect(promise).resolves.toEqual([])
        expect(onProgress).toHaveBeenCalledTimes(3)
        expect(onProgress).toHaveBeenLastCalledWith(3, 3)
    })

    it('reports the failed widths once per run instead of swallowing them', async () => {
        const promise = captureResponsiveScreenshots([320, 768, 1440])
        await jest.runAllTimersAsync()
        await promise

        expect(toolbarLogger.warn).toHaveBeenCalledTimes(3)
        expect(captureToolbarException).toHaveBeenCalledTimes(1)
        expect(captureToolbarException).toHaveBeenCalledWith(expect.any(Error), 'responsive_screenshot', {
            failed_widths: [320, 768, 1440],
            captured_count: 0,
            requested_count: 3,
        })
    })

    it('waits for a stalled image once and leaves it blank at every width', async () => {
        const image = document.createElement('img')
        image.src = 'https://example.com/stalled.png'
        document.body.appendChild(image)
        const capturedSources: (string | null)[] = []
        ;(captureElementScreenshot as jest.Mock).mockImplementation(async (element: HTMLElement) => {
            capturedSources.push(element.querySelector('img')?.getAttribute('src') ?? null)
            return new Blob()
        })

        const started = Date.now()
        const elapsed = captureResponsiveScreenshots([320, 768, 1440]).then(() => Date.now() - started)
        await jest.runAllTimersAsync()

        expect(await elapsed).toBeLessThan(2 * 4000)
        expect(capturedSources).toEqual([BLANK_IMAGE, BLANK_IMAGE, BLANK_IMAGE])
    })
})
