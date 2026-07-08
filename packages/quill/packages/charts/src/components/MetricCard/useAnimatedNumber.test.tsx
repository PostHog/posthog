import { act, renderHook } from '@testing-library/react'

import { useAnimatedNumber } from './useAnimatedNumber'

interface RafController {
    step: (now: number) => void
    pendingCount: () => number
    teardown: () => void
}

function installControllableRaf(): RafController {
    const queue: FrameRequestCallback[] = []
    const originalRaf = global.requestAnimationFrame
    const originalCancel = global.cancelAnimationFrame
    const originalPerf = global.performance.now
    let nextId = 1
    const handles = new Map<number, FrameRequestCallback>()

    global.requestAnimationFrame = ((cb: FrameRequestCallback) => {
        const id = nextId++
        handles.set(id, cb)
        queue.push(cb)
        return id
    }) as typeof global.requestAnimationFrame

    global.cancelAnimationFrame = ((id: number) => {
        const cb = handles.get(id)
        if (cb) {
            const i = queue.indexOf(cb)
            if (i >= 0) {
                queue.splice(i, 1)
            }
            handles.delete(id)
        }
    }) as typeof global.cancelAnimationFrame

    global.performance.now = jest.fn(() => 0)

    return {
        step: (now: number) => {
            ;(global.performance.now as jest.Mock).mockReturnValue(now)
            const callbacks = queue.splice(0, queue.length)
            handles.clear()
            act(() => {
                callbacks.forEach((cb) => cb(now))
            })
        },
        pendingCount: () => queue.length,
        teardown: () => {
            global.requestAnimationFrame = originalRaf
            global.cancelAnimationFrame = originalCancel
            global.performance.now = originalPerf
        },
    }
}

describe('useAnimatedNumber', () => {
    let raf: RafController

    beforeEach(() => {
        raf = installControllableRaf()
    })

    afterEach(() => {
        raf.teardown()
    })

    it('returns the target on initial render', () => {
        const { result } = renderHook(() => useAnimatedNumber(42))
        expect(result.current).toBe(42)
    })

    it.each([
        ['zero', 0],
        ['negative', -10],
    ])('snaps immediately when duration is %s', (_label, duration) => {
        const { result, rerender } = renderHook(({ target }) => useAnimatedNumber(target, duration), {
            initialProps: { target: 0 },
        })
        rerender({ target: 100 })
        expect(result.current).toBe(100)
        expect(raf.pendingCount()).toBe(0)
    })

    it.each([
        ['NaN', NaN],
        ['Infinity', Infinity],
        ['-Infinity', -Infinity],
    ])('snaps immediately when target is %s', (_label, target) => {
        const { result, rerender } = renderHook(({ t }: { t: number }) => useAnimatedNumber(t, 350), {
            initialProps: { t: 0 },
        })
        rerender({ t: target })
        expect(result.current).toBe(target)
        expect(raf.pendingCount()).toBe(0)
    })

    it('does not schedule animation when target is unchanged', () => {
        const { rerender } = renderHook(({ target }) => useAnimatedNumber(target, 350), {
            initialProps: { target: 10 },
        })
        rerender({ target: 10 })
        expect(raf.pendingCount()).toBe(0)
    })

    it('animates from the previous value toward the new target across frames', () => {
        const { result, rerender } = renderHook(({ target }) => useAnimatedNumber(target, 100), {
            initialProps: { target: 0 },
        })
        rerender({ target: 100 })
        expect(raf.pendingCount()).toBe(1)
        expect(result.current).toBe(0)

        raf.step(50)
        expect(result.current).toBeGreaterThan(0)
        expect(result.current).toBeLessThan(100)

        raf.step(100)
        expect(result.current).toBe(100)
        expect(raf.pendingCount()).toBe(0)
    })

    it('restarts from the currently-displayed value when target changes mid-animation', () => {
        const { result, rerender } = renderHook(({ target }) => useAnimatedNumber(target, 100), {
            initialProps: { target: 0 },
        })
        rerender({ target: 100 })
        raf.step(40)
        const midValue = result.current
        expect(midValue).toBeGreaterThan(0)
        expect(midValue).toBeLessThan(100)

        rerender({ target: 200 })
        expect(result.current).toBe(midValue)

        raf.step(100)
        expect(result.current).toBeGreaterThan(midValue)
    })

    it('cancels the pending frame on unmount', () => {
        const { rerender, unmount } = renderHook(({ target }) => useAnimatedNumber(target, 100), {
            initialProps: { target: 0 },
        })
        rerender({ target: 100 })
        expect(raf.pendingCount()).toBe(1)
        unmount()
        expect(raf.pendingCount()).toBe(0)
    })
})
