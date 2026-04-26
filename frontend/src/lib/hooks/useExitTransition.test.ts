import { act, renderHook } from '@testing-library/react'

import { useExitTransition } from './useExitTransition'

describe('useExitTransition', () => {
    let rafCallbacks: FrameRequestCallback[] = []
    let originalRaf: typeof window.requestAnimationFrame
    let originalCancelRaf: typeof window.cancelAnimationFrame

    beforeEach(() => {
        jest.useFakeTimers()
        rafCallbacks = []
        originalRaf = window.requestAnimationFrame
        originalCancelRaf = window.cancelAnimationFrame
        window.requestAnimationFrame = ((cb: FrameRequestCallback): number => {
            rafCallbacks.push(cb)
            return rafCallbacks.length
        }) as typeof window.requestAnimationFrame
        window.cancelAnimationFrame = ((handle: number): void => {
            rafCallbacks[handle - 1] = () => undefined
        }) as typeof window.cancelAnimationFrame
    })

    afterEach(() => {
        jest.clearAllTimers()
        jest.useRealTimers()
        window.requestAnimationFrame = originalRaf
        window.cancelAnimationFrame = originalCancelRaf
    })

    function flushRaf(): void {
        const pending = rafCallbacks
        rafCallbacks = []
        pending.forEach((cb) => cb(0))
    }

    it.each([
        ['initially in', true],
        ['initially out', false],
    ])('matches the initial value when %s', (_label, initial) => {
        const { result } = renderHook(({ isIn }) => useExitTransition(isIn, 200), { initialProps: { isIn: initial } })
        expect(result.current).toEqual({ mounted: initial, visible: initial })
    })

    it('mounts immediately on enter and flips visible on the next frame', () => {
        const { result, rerender } = renderHook(({ isIn }) => useExitTransition(isIn, 200), {
            initialProps: { isIn: false },
        })
        expect(result.current).toEqual({ mounted: false, visible: false })

        rerender({ isIn: true })
        expect(result.current).toEqual({ mounted: true, visible: false })

        act(() => flushRaf())
        expect(result.current).toEqual({ mounted: true, visible: true })
    })

    it('flips visible immediately on exit and unmounts after the duration', () => {
        const { result, rerender } = renderHook(({ isIn }) => useExitTransition(isIn, 200), {
            initialProps: { isIn: true },
        })
        expect(result.current).toEqual({ mounted: true, visible: true })

        rerender({ isIn: false })
        expect(result.current).toEqual({ mounted: true, visible: false })

        act(() => jest.advanceTimersByTime(199))
        expect(result.current.mounted).toBe(true)

        act(() => jest.advanceTimersByTime(1))
        expect(result.current).toEqual({ mounted: false, visible: false })
    })

    it('cancels a pending unmount when re-entering mid-exit', () => {
        const { result, rerender } = renderHook(({ isIn }) => useExitTransition(isIn, 200), {
            initialProps: { isIn: true },
        })
        act(() => flushRaf())
        rerender({ isIn: false })
        act(() => jest.advanceTimersByTime(100))
        rerender({ isIn: true })
        act(() => jest.advanceTimersByTime(200))
        expect(result.current.mounted).toBe(true)
        act(() => flushRaf())
        expect(result.current).toEqual({ mounted: true, visible: true })
    })

    it('cleans up timers on unmount', () => {
        const { rerender, unmount } = renderHook(({ isIn }) => useExitTransition(isIn, 200), {
            initialProps: { isIn: true },
        })
        rerender({ isIn: false })
        unmount()
        expect(jest.getTimerCount()).toBe(0)
    })
})
