import * as React from 'react'

import { CodeCanvasLink } from './CodeCanvasLink'

jest.mock('react', () => ({
    ...jest.requireActual('react'),
    useEffect: jest.fn(),
}))

describe('CodeCanvasLink', () => {
    afterEach(() => {
        jest.restoreAllMocks()
        jest.clearAllMocks()
    })

    it('closes the bridge page five seconds after opening PostHog Desktop', () => {
        const originalLocation = window.location
        const closeSpy = jest.spyOn(window, 'close').mockImplementation()
        const clearTimeoutSpy = jest.spyOn(window, 'clearTimeout')
        let closePage: (() => void) | undefined

        Object.defineProperty(window, 'location', {
            configurable: true,
            writable: true,
            value: { ...originalLocation, href: originalLocation.href },
        })
        jest.spyOn(window, 'setTimeout').mockImplementation((handler) => {
            closePage = handler as () => void
            return 1
        })

        try {
            CodeCanvasLink({ channelId: 'channel-1', dashboardId: 'dashboard-1' })

            const openDesktopAndScheduleClose = jest.mocked(React.useEffect).mock.calls[0][0]
            const cleanup = openDesktopAndScheduleClose()

            expect(window.location.href).toBe('posthog-code://canvas/channel-1/dashboard-1')
            expect(window.setTimeout).toHaveBeenCalledWith(expect.any(Function), 5000)

            closePage?.()
            expect(closeSpy).toHaveBeenCalledTimes(1)

            cleanup?.()
            expect(clearTimeoutSpy).toHaveBeenCalledWith(1)
        } finally {
            Object.defineProperty(window, 'location', {
                configurable: true,
                writable: true,
                value: originalLocation,
            })
        }
    })
})
