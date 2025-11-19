import { act, renderHook } from '@testing-library/react'

import { usePeriodicRerender } from './usePeriodicRerender'

describe('usePeriodicRerender', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        // Set up initial document state
        Object.defineProperty(document, 'hidden', {
            writable: true,
            value: false,
        })
        Object.defineProperty(document, 'hasFocus', {
            writable: true,
            value: jest.fn(() => true),
        })
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

        // Initial render
        expect(renderCount).toBe(1)

        // Advance time by 1 second
        act(() => {
            jest.advanceTimersByTime(1000)
        })
        expect(renderCount).toBe(2)

        // Advance time by another 1 second
        act(() => {
            jest.advanceTimersByTime(1000)
        })
        expect(renderCount).toBe(3)
    })

    it('should stop rerenders when page becomes hidden', () => {
        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        // Initial render
        expect(renderCount).toBe(1)

        // Advance time by 1 second
        act(() => {
            jest.advanceTimersByTime(1000)
        })
        expect(renderCount).toBe(2)

        // Hide the page
        Object.defineProperty(document, 'hidden', { value: true })
        act(() => {
            document.dispatchEvent(new Event('visibilitychange'))
        })

        // Advance time by 2 seconds - should not trigger rerenders
        act(() => {
            jest.advanceTimersByTime(2000)
        })
        expect(renderCount).toBe(2)
    })

    it('should resume rerenders (with immediate trigger) when page becomes visible again', () => {
        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        // Initial render
        expect(renderCount).toBe(1)

        // Hide the page
        Object.defineProperty(document, 'hidden', { value: true })
        act(() => {
            document.dispatchEvent(new Event('visibilitychange'))
        })

        // Make page visible again - should trigger immediate rerender
        Object.defineProperty(document, 'hidden', { value: false })
        act(() => {
            document.dispatchEvent(new Event('visibilitychange'))
        })
        expect(renderCount).toBe(2)

        // Advance time by 1 second - should trigger another rerender
        act(() => {
            jest.advanceTimersByTime(1000)
        })
        expect(renderCount).toBe(3)
    })

    it('should stop rerenders when window loses focus', () => {
        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        // Initial render
        expect(renderCount).toBe(1)

        // Advance time by 1 second
        act(() => {
            jest.advanceTimersByTime(1000)
        })
        expect(renderCount).toBe(2)

        // Window loses focus
        Object.defineProperty(document, 'hasFocus', { value: jest.fn(() => false) })
        act(() => {
            window.dispatchEvent(new Event('blur'))
        })

        // Advance time by 2 seconds - should not trigger rerenders
        act(() => {
            jest.advanceTimersByTime(2000)
        })
        expect(renderCount).toBe(2)
    })

    it('should resume rerenders (with immediate trigger) when window gains focus again', () => {
        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        // Initial render
        expect(renderCount).toBe(1)

        // Window loses focus
        Object.defineProperty(document, 'hasFocus', { value: jest.fn(() => false) })
        act(() => {
            window.dispatchEvent(new Event('blur'))
        })

        // Window gains focus again - should trigger immediate rerender
        Object.defineProperty(document, 'hasFocus', { value: jest.fn(() => true) })
        act(() => {
            window.dispatchEvent(new Event('focus'))
        })
        expect(renderCount).toBe(2)

        // Advance time by 1 second - should trigger another rerender
        act(() => {
            jest.advanceTimersByTime(1000)
        })
        expect(renderCount).toBe(3)
    })

    it('should not start interval if page is hidden on mount', () => {
        Object.defineProperty(document, 'hidden', { value: true })

        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        // Initial render
        expect(renderCount).toBe(1)

        // Advance time by 2 seconds - should not trigger rerenders
        act(() => {
            jest.advanceTimersByTime(2000)
        })
        expect(renderCount).toBe(1)
    })

    it('should not start interval if window is unfocused on mount', () => {
        Object.defineProperty(document, 'hasFocus', { value: jest.fn(() => false) })

        let renderCount = 0
        renderHook(() => {
            usePeriodicRerender(1000)
            renderCount++
        })

        // Initial render
        expect(renderCount).toBe(1)

        // Advance time by 2 seconds - should not trigger rerenders
        act(() => {
            jest.advanceTimersByTime(2000)
        })
        expect(renderCount).toBe(1)
    })

    it('should clean up interval on unmount', () => {
        const { unmount } = renderHook(() => usePeriodicRerender(1000))

        // Unmount the hook
        unmount()

        // Verify no timers are left
        expect(jest.getTimerCount()).toBe(0)
    })
})
