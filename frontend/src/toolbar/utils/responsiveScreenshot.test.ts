import { captureResponsiveScreenshots } from '~/toolbar/utils/responsiveScreenshot'

jest.mock('~/toolbar/utils/screenshot', () => ({
    captureElementScreenshot: jest.fn(() => Promise.reject(new Error('capture failed'))),
}))

describe('captureResponsiveScreenshots', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    it('skips every failed width and resolves to an empty array instead of throwing', async () => {
        const onProgress = jest.fn()
        const promise = captureResponsiveScreenshots([320, 768, 1440], onProgress)
        await jest.runAllTimersAsync()

        await expect(promise).resolves.toEqual([])
        expect(onProgress).toHaveBeenCalledTimes(3)
        expect(onProgress).toHaveBeenLastCalledWith(3, 3)
    })
})
