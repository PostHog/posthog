import { act, renderHook } from '@testing-library/react'

import { usePeriodicRerender } from './usePeriodicRerender'

describe('usePeriodicRerender', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        Object.defineProperty(document, 'hidden', { writable: true, value: false })
        Object.defineProperty(document, 'hasFocus', { writable: true, value: jest.fn(() => true) })
    })

    afterEach(() => {
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
    })

    it('should trigger rerenders at the specified interval when page is active', () => {
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

    it.each([
        ['page becomes hidden', 'hidden', true, 'visibilitychange'],
        ['window loses focus', 'hasFocus', jest.fn(() => false), 'blur'],
    ])('should stop rerenders when %s', (_, property, value, event) => {
        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        expect(renderCount).toBe(1)

        act(() => jest.advanceTimersByTime(1000))
        expect(renderCount).toBe(2)

        Object.defineProperty(document, property, { value })
        act(() => (event === 'visibilitychange' ? document : window).dispatchEvent(new Event(event)))

        act(() => jest.advanceTimersByTime(2000))
        expect(renderCount).toBe(2)
    })

    it.each([
        ['page becomes visible', 'hidden', false, 'visibilitychange'],
        ['window gains focus', 'hasFocus', jest.fn(() => true), 'focus'],
    ])('should resume rerenders with immediate trigger when %s', (_, property, value, event) => {
        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        expect(renderCount).toBe(1)

        const inactiveValue = property === 'hidden' ? true : jest.fn(() => false)
        const inactiveEvent = property === 'hidden' ? 'visibilitychange' : 'blur'
        Object.defineProperty(document, property, { value: inactiveValue })
        act(() => (inactiveEvent === 'visibilitychange' ? document : window).dispatchEvent(new Event(inactiveEvent)))

        Object.defineProperty(document, property, { value })
        act(() => (event === 'visibilitychange' ? document : window).dispatchEvent(new Event(event)))
        expect(renderCount).toBe(2)

        act(() => jest.advanceTimersByTime(1000))
        expect(renderCount).toBe(3)
    })

    it.each([
        ['page is hidden', 'hidden', true],
        ['window is unfocused', 'hasFocus', jest.fn(() => false)],
    ])('should not start interval if %s on mount', (_, property, value) => {
        Object.defineProperty(document, property, { value })

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
