import { act, renderHook } from '@testing-library/react'

import { useVisualViewportBounds } from './useVisualViewportBounds'

describe('useVisualViewportBounds', () => {
    let listeners: Record<string, (() => void)[]>
    let viewport: { height: number; offsetTop: number }

    beforeEach(() => {
        listeners = {}
        viewport = { height: 844, offsetTop: 0 }
        Object.defineProperty(window, 'visualViewport', {
            configurable: true,
            value: {
                get height() {
                    return viewport.height
                },
                get offsetTop() {
                    return viewport.offsetTop
                },
                addEventListener: (type: string, listener: () => void) => {
                    listeners[type] = [...(listeners[type] ?? []), listener]
                },
                removeEventListener: (type: string, listener: () => void) => {
                    listeners[type] = (listeners[type] ?? []).filter((l) => l !== listener)
                },
            },
        })
    })

    afterEach(() => {
        Object.defineProperty(window, 'visualViewport', { configurable: true, value: undefined })
        document.documentElement.removeAttribute('style')
    })

    const bounds = (): (string | null)[] => [
        document.documentElement.style.getPropertyValue('--visual-viewport-height') || null,
        document.documentElement.style.getPropertyValue('--visual-viewport-offset-top') || null,
    ]

    const resizeTo = (height: number, offsetTop: number): void => {
        viewport = { height, offsetTop }
        act(() => listeners.resize?.forEach((l) => l()))
    }

    it('tracks the viewport while enabled and cleans up on unmount', () => {
        const { unmount } = renderHook(() => useVisualViewportBounds(true))
        expect(bounds()).toEqual(['844px', '0px'])

        // The on-screen keyboard opening
        resizeTo(504, 60)
        expect(bounds()).toEqual(['504px', '60px'])

        unmount()
        expect(bounds()).toEqual([null, null])
    })

    it('publishes nothing while disabled', () => {
        renderHook(() => useVisualViewportBounds(false))
        expect(bounds()).toEqual([null, null])
    })

    it('keeps tracking until the last subscriber unmounts', () => {
        const first = renderHook(() => useVisualViewportBounds(true))
        const second = renderHook(() => useVisualViewportBounds(true))

        first.unmount()
        resizeTo(504, 0)
        expect(bounds()).toEqual(['504px', '0px'])

        second.unmount()
        expect(bounds()).toEqual([null, null])
    })
})
