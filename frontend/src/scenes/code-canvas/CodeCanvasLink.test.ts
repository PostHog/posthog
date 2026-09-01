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

    it('closes the bridge page after the desktop app hides it', () => {
        const originalLocation = window.location
        const closeSpy = jest.spyOn(window, 'close').mockImplementation()
        const clearTimeoutSpy = jest.spyOn(window, 'clearTimeout')
        const visibilityStateSpy = jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
        const timers = new Map<number, () => void>()
        let nextTimerId = 1
        let visibilityChangeHandler: EventListener | undefined

        Object.defineProperty(window, 'location', {
            configurable: true,
            writable: true,
            value: { ...originalLocation, href: originalLocation.href },
        })
        jest.spyOn(window, 'setTimeout').mockImplementation((handler, delay) => {
            timers.set(delay as number, handler as () => void)
            return nextTimerId++
        })
        jest.spyOn(document, 'addEventListener').mockImplementation((type, listener) => {
            if (type === 'visibilitychange') {
                visibilityChangeHandler = listener as EventListener
            }
        })

        try {
            CodeCanvasLink({ channelId: 'channel-1', dashboardId: 'dashboard-1' })

            const openDesktopAndWatchForIt = jest.mocked(React.useEffect).mock.calls[0][0]
            const cleanup = openDesktopAndWatchForIt()

            expect(window.location.href).toBe('posthog-code://canvas/channel-1/dashboard-1')
            expect(timers.has(5000)).toBe(false)

            visibilityStateSpy.mockReturnValue('hidden')
            visibilityChangeHandler?.(new Event('visibilitychange'))

            expect(timers.get(5000)).toEqual(expect.any(Function))
            timers.get(5000)?.()
            expect(closeSpy).toHaveBeenCalledTimes(1)

            cleanup?.()
            expect(clearTimeoutSpy).toHaveBeenCalledWith(1)
            expect(clearTimeoutSpy).toHaveBeenCalledWith(2)
        } finally {
            Object.defineProperty(window, 'location', {
                configurable: true,
                writable: true,
                value: originalLocation,
            })
        }
    })
})
