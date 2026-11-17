import { act, cleanup, renderHook } from '@testing-library/react'

import { useViewportPixelRatio } from './useViewportPixelRatio'

describe('useViewportPixelRatio', () => {
    const originalDpr = window.devicePixelRatio
    let onViewportResize = (): void => {}
    const viewport = {
        scale: 1,
        addEventListener: (_event: string, listener: () => void) => {
            onViewportResize = listener
        },
        removeEventListener: () => {},
    }

    beforeEach(() => {
        viewport.scale = 1
        Object.defineProperty(window, 'devicePixelRatio', { value: 1, configurable: true })
        Object.defineProperty(window, 'visualViewport', { value: viewport, configurable: true })
        jest.useFakeTimers()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        Object.defineProperty(window, 'visualViewport', { value: undefined, configurable: true })
        Object.defineProperty(window, 'devicePixelRatio', { value: originalDpr, configurable: true })
    })

    it.each([
        ['a pinch-zoom', 2, 1],
        ['a move to a screen with another pixel ratio', 1, 2],
    ])('reports the new ratio only once the viewport settles after %s', (_, zoom, dpr) => {
        const { result } = renderHook(() => useViewportPixelRatio())
        expect(result.current).toBe(1)

        viewport.scale = zoom
        Object.defineProperty(window, 'devicePixelRatio', { value: dpr, configurable: true })
        act(() => onViewportResize())
        expect(result.current).toBe(1)

        act(() => {
            jest.advanceTimersByTime(150)
        })
        expect(result.current).toBe(2)
    })
})
