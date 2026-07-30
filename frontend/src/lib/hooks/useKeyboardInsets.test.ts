import { act, renderHook } from '@testing-library/react'

import { useKeyboardInsets } from './useKeyboardInsets'

// Every renderHook here unmounts explicitly: this repo loads jest.setup.ts via `setupFiles`, which
// runs before the test framework installs `afterEach`, so testing-library never registers its auto
// cleanup. A leaked subscriber would keep the hook attached to the previous test's listener stub.
describe('useKeyboardInsets', () => {
    const LAYOUT_HEIGHT = 844
    let listeners: Record<string, (() => void)[]>
    let viewport: { height: number; offsetTop: number }

    beforeEach(() => {
        listeners = {}
        viewport = { height: LAYOUT_HEIGHT, offsetTop: 0 }
        Object.defineProperty(document.documentElement, 'clientHeight', {
            configurable: true,
            value: LAYOUT_HEIGHT,
        })
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

    const insets = (): (string | null)[] => [
        document.documentElement.style.getPropertyValue('--keyboard-inset-bottom') || null,
        document.documentElement.style.getPropertyValue('--keyboard-inset-top') || null,
    ]

    const resizeTo = (height: number, offsetTop: number): void => {
        viewport = { height, offsetTop }
        act(() => listeners.resize?.forEach((l) => l()))
    }

    it('publishes the keyboard inset while enabled and cleans up on unmount', () => {
        const { unmount } = renderHook(() => useKeyboardInsets(true))
        expect(insets()).toEqual([null, null])

        resizeTo(504, 0)
        expect(insets()).toEqual(['340px', '0px'])

        unmount()
        expect(insets()).toEqual([null, null])
    })

    // The visual viewport is legitimately shorter than the layout viewport in iframes and embedded
    // contexts. Reacting to that would clamp every modal down and clip its content.
    it.each([
        { name: 'nothing occluding', height: LAYOUT_HEIGHT },
        { name: 'a scrollbar-sized gap', height: LAYOUT_HEIGHT - 15 },
        { name: 'a gap just under the keyboard floor', height: LAYOUT_HEIGHT - 99 },
    ])('publishes nothing for $name', ({ height }) => {
        const { unmount } = renderHook(() => useKeyboardInsets(true))
        resizeTo(height, 0)
        expect(insets()).toEqual([null, null])
        unmount()
    })

    // iOS scrolls the visual viewport within the layout viewport that `position: fixed` resolves against.
    it('counts the offset as occlusion and reports it as the top inset', () => {
        const { unmount } = renderHook(() => useKeyboardInsets(true))
        resizeTo(504, 60)
        expect(insets()).toEqual(['280px', '60px'])
        unmount()
    })

    it('drops back to the defaults when the keyboard closes', () => {
        const { unmount } = renderHook(() => useKeyboardInsets(true))
        resizeTo(504, 0)
        resizeTo(LAYOUT_HEIGHT, 0)
        expect(insets()).toEqual([null, null])
        unmount()
    })

    it('publishes nothing while disabled', () => {
        const { unmount } = renderHook(() => useKeyboardInsets(false))
        resizeTo(504, 0)
        expect(insets()).toEqual([null, null])
        unmount()
    })

    it('keeps tracking until the last subscriber unmounts', () => {
        const first = renderHook(() => useKeyboardInsets(true))
        const second = renderHook(() => useKeyboardInsets(true))

        first.unmount()
        resizeTo(504, 0)
        expect(insets()).toEqual(['340px', '0px'])

        second.unmount()
        expect(insets()).toEqual([null, null])
    })
})
