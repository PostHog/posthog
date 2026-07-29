import { act, renderHook } from '@testing-library/react'

import { useAnimatedPresence } from './useAnimatedPresence'

describe('useAnimatedPresence', () => {
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

    function runFrame(): void {
        const pending = rafCallbacks
        rafCallbacks = []
        pending.forEach((cb) => cb(0))
    }

    // Drains nested RAFs too, so callers that just want the enter to settle
    // don't need to know how many frames the flip takes.
    function flushRaf(): void {
        while (rafCallbacks.length) {
            runFrame()
        }
    }

    it.each([
        ['initially in', true],
        ['initially out', false],
    ])('matches the initial value when %s', (_label, initial) => {
        const { result } = renderHook(({ isIn }) => useAnimatedPresence(isIn, 200), { initialProps: { isIn: initial } })
        expect(result.current).toEqual({ rendered: initial, shown: initial })
    })

    it('renders immediately on enter but holds shown for a frame so the hidden state paints first', () => {
        const { result, rerender } = renderHook(({ isIn }) => useAnimatedPresence(isIn, 200), {
            initialProps: { isIn: false },
        })
        expect(result.current).toEqual({ rendered: false, shown: false })

        rerender({ isIn: true })
        expect(result.current).toEqual({ rendered: true, shown: false })

        // First frame paints the mounted-but-hidden state; shown must not flip
        // yet, otherwise the browser coalesces both into one paint and the
        // enter transition never runs.
        act(() => runFrame())
        expect(result.current).toEqual({ rendered: true, shown: false })

        // Second frame flips shown, so the transition animates from the
        // already-painted hidden state.
        act(() => runFrame())
        expect(result.current).toEqual({ rendered: true, shown: true })
    })

    it('flips shown synchronously via a reflow when given a ref, without waiting for a frame', () => {
        const ref = { current: document.createElement('div') }
        const { result, rerender } = renderHook(({ isIn }) => useAnimatedPresence(isIn, 200, ref), {
            initialProps: { isIn: false },
        })
        expect(result.current).toEqual({ rendered: false, shown: false })

        // The layout effect forces a reflow and flips shown in the same commit —
        // no RAF is scheduled, so the enter can't be lost to paint coalescing.
        rerender({ isIn: true })
        expect(result.current).toEqual({ rendered: true, shown: true })
        expect(rafCallbacks).toHaveLength(0)
    })

    it('flips shown immediately on exit and unrenders after the duration', () => {
        const { result, rerender } = renderHook(({ isIn }) => useAnimatedPresence(isIn, 200), {
            initialProps: { isIn: true },
        })
        expect(result.current).toEqual({ rendered: true, shown: true })

        rerender({ isIn: false })
        expect(result.current).toEqual({ rendered: true, shown: false })

        act(() => jest.advanceTimersByTime(199))
        expect(result.current.rendered).toBe(true)

        act(() => jest.advanceTimersByTime(1))
        expect(result.current).toEqual({ rendered: false, shown: false })
    })

    it('cancels a pending unrender when re-entering mid-exit', () => {
        const { result, rerender } = renderHook(({ isIn }) => useAnimatedPresence(isIn, 200), {
            initialProps: { isIn: true },
        })
        act(() => flushRaf())
        rerender({ isIn: false })
        act(() => jest.advanceTimersByTime(100))
        rerender({ isIn: true })
        act(() => jest.advanceTimersByTime(200))
        expect(result.current.rendered).toBe(true)
        act(() => flushRaf())
        expect(result.current).toEqual({ rendered: true, shown: true })
    })

    it('cleans up timers on unmount', () => {
        const { rerender, unmount } = renderHook(({ isIn }) => useAnimatedPresence(isIn, 200), {
            initialProps: { isIn: true },
        })
        rerender({ isIn: false })
        unmount()
        expect(jest.getTimerCount()).toBe(0)
    })

    it('does not schedule a timer when initially out', () => {
        renderHook(() => useAnimatedPresence(false, 200))
        expect(jest.getTimerCount()).toBe(0)
    })

    it('cancels mid-enter exit before the RAF fires', () => {
        const { result, rerender } = renderHook(({ isIn }) => useAnimatedPresence(isIn, 200), {
            initialProps: { isIn: false },
        })
        rerender({ isIn: true })
        rerender({ isIn: false })
        expect(result.current).toEqual({ rendered: true, shown: false })

        act(() => jest.advanceTimersByTime(200))
        expect(result.current).toEqual({ rendered: false, shown: false })
    })

    it.each([
        ['enter-exit-enter-exit hammering', [true, false, true, false]],
        ['exit-then-enter-then-exit before timers fire', [false, true, false]],
    ])('settles correctly under %s', (_label, sequence) => {
        const { result, rerender } = renderHook(({ isIn }) => useAnimatedPresence(isIn, 200), {
            initialProps: { isIn: sequence[0] },
        })
        for (const isIn of sequence.slice(1)) {
            rerender({ isIn })
        }

        const final = sequence[sequence.length - 1]
        if (final) {
            expect(result.current.rendered).toBe(true)
            act(() => flushRaf())
            expect(result.current).toEqual({ rendered: true, shown: true })
        } else {
            expect(result.current.shown).toBe(false)
            act(() => jest.advanceTimersByTime(200))
            expect(result.current).toEqual({ rendered: false, shown: false })
        }
    })
})
