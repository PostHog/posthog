import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { openDeepLinkWithFallback, openDesktopApp } from './openDesktopApp'

describe('openDesktopApp', () => {
    let openSpy: jest.SpyInstance
    let infoSpy: jest.SpyInstance

    beforeEach(() => {
        jest.useFakeTimers()
        openSpy = jest.spyOn(window, 'open').mockImplementation(() => null)
        infoSpy = jest.spyOn(lemonToast, 'info').mockImplementation(() => 0)
    })

    afterEach(() => {
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
        openSpy.mockRestore()
        infoSpy.mockRestore()
    })

    it('fires the deep link and warns when nothing handles it', () => {
        openDeepLinkWithFallback('posthog-code://task/abc', { missingMessage: 'nope', downloadUrl: 'https://dl' })

        expect(openSpy).toHaveBeenCalledWith('posthog-code://task/abc', '_blank')
        expect(infoSpy).not.toHaveBeenCalled()

        jest.advanceTimersByTime(3000)

        expect(infoSpy).toHaveBeenCalledTimes(1)
        expect(infoSpy.mock.calls[0][0]).toBe('nope')
        expect(infoSpy.mock.calls[0][1].button.label).toBe('Download')
    })

    it('stays silent once the OS hands off to the app', () => {
        openDeepLinkWithFallback('posthog-code://task/abc', { missingMessage: 'nope' })

        // A hand-off blurs or hides the tab before the grace period elapses.
        window.dispatchEvent(new Event('blur'))
        jest.advanceTimersByTime(3000)

        expect(infoSpy).not.toHaveBeenCalled()
    })

    it('builds the desktop scheme URL from a path', () => {
        // NODE_ENV is `test` here, so DESKTOP_SCHEME resolves to the production scheme.
        openDesktopApp('task/abc')

        expect(openSpy).toHaveBeenCalledWith('posthog-code://task/abc', '_blank')
    })
})
