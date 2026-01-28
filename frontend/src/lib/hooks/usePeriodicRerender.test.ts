import { act, renderHook } from '@testing-library/react'

import { usePeriodicRerender } from './usePeriodicRerender'

describe('usePeriodicRerender', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        Object.defineProperty(document, 'hidden', { writable: true, value: false })
    })

    afterEach(() => {
        jest.clearAllTimers()
        jest.useRealTimers()
    })

    it('should trigger rerenders at the specified interval when page is visible', () => {
        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        expect(renderCount).toBe(1)

        act(() => jest.advanceTimersByTime(1000))
        expect(renderCount).toBe(2)

        act(() => jest.advanceTimersByTime(1000))
        expect(renderCount).toBe(3)
    })

    it('should stop rerenders when page becomes hidden', () => {
        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        expect(renderCount).toBe(1)

        act(() => jest.advanceTimersByTime(1000))
        expect(renderCount).toBe(2)

        Object.defineProperty(document, 'hidden', { value: true })
        act(() => document.dispatchEvent(new Event('visibilitychange')))
        // Visibility change causes one extra rerender from state update
        expect(renderCount).toBe(3)

        act(() => jest.advanceTimersByTime(2000))
        // Should not trigger any more rerenders
        expect(renderCount).toBe(3)
    })

    it('should resume rerenders with immediate trigger when page becomes visible', () => {
        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        expect(renderCount).toBe(1)

        Object.defineProperty(document, 'hidden', { value: true })
        act(() => document.dispatchEvent(new Event('visibilitychange')))
        // Visibility change causes one extra rerender from state update
        expect(renderCount).toBe(2)

        Object.defineProperty(document, 'hidden', { value: false })
        act(() => document.dispatchEvent(new Event('visibilitychange')))
        // Visibility change (state update) + immediate trigger = two more rerenders
        expect(renderCount).toBe(4)

        act(() => jest.advanceTimersByTime(1000))
        expect(renderCount).toBe(5)
    })

    it('should not start interval if page is hidden on mount', () => {
        Object.defineProperty(document, 'hidden', { value: true })

        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        expect(renderCount).toBe(1)

        act(() => jest.advanceTimersByTime(2000))
        expect(renderCount).toBe(1)
    })

    it('should clean up interval on unmount', () => {
        const { unmount } = renderHook(() => usePeriodicRerender(1000))

        unmount()

        expect(jest.getTimerCount()).toBe(0)
    })
})
