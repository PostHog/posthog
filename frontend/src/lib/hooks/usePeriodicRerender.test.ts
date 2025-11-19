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

        act(() => jest.advanceTimersByTime(2000))
        expect(renderCount).toBe(2)
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

        Object.defineProperty(document, 'hidden', { value: false })
        act(() => document.dispatchEvent(new Event('visibilitychange')))
        expect(renderCount).toBe(2)

        act(() => jest.advanceTimersByTime(1000))
        expect(renderCount).toBe(3)
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
