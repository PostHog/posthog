import { act, renderHook } from '@testing-library/react'

import { usePageVisibility, usePageVisibilityCb } from './usePageVisibility'

function setHidden(hidden: boolean): void {
    Object.defineProperty(document, 'hidden', { configurable: true, value: hidden })
    Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        value: hidden ? 'hidden' : 'visible',
    })
    document.dispatchEvent(new Event('visibilitychange'))
}

describe('usePageVisibility hooks', () => {
    afterEach(() => {
        Object.defineProperty(document, 'hidden', { configurable: true, value: false })
        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    })

    describe.each([
        { name: 'mounted while visible, becomes hidden, becomes visible', initialHidden: false },
        { name: 'mounted while hidden, becomes visible, becomes hidden', initialHidden: true },
    ])('usePageVisibilityCb — $name', ({ initialHidden }) => {
        it('fires the callback with the initial state on mount and on every change', () => {
            Object.defineProperty(document, 'hidden', { configurable: true, value: initialHidden })
            Object.defineProperty(document, 'visibilityState', {
                configurable: true,
                value: initialHidden ? 'hidden' : 'visible',
            })

            const calls: boolean[] = []
            const callback = (visible: boolean): void => {
                calls.push(visible)
            }

            renderHook(() => usePageVisibilityCb(callback))

            expect(calls).toEqual([!initialHidden])

            act(() => setHidden(!initialHidden))
            act(() => setHidden(initialHidden))

            expect(calls).toEqual([!initialHidden, initialHidden, !initialHidden])
        })
    })

    it('usePageVisibilityCb does not re-fire on parent re-render with a new callback identity', () => {
        const calls: boolean[] = []

        const { rerender } = renderHook(
            ({ tag }: { tag: number }) => {
                // tag captured in the closure forces a fresh callback identity per render.
                usePageVisibilityCb((visible) => {
                    calls.push(visible)
                    void tag
                })
            },
            { initialProps: { tag: 0 } }
        )

        expect(calls).toHaveLength(1)

        rerender({ tag: 1 })
        rerender({ tag: 2 })
        rerender({ tag: 3 })

        // Still only the one mount-time call — no extra dispatches from re-renders.
        expect(calls).toHaveLength(1)

        // The latest callback identity still fires on a real visibility change.
        act(() => setHidden(true))
        expect(calls).toEqual([true, false])
    })

    it('usePageVisibilityCb invokes the latest callback after a parent re-render', () => {
        const calls: Array<{ from: 'first' | 'second'; visible: boolean }> = []

        const { rerender } = renderHook(
            ({ which }: { which: 'first' | 'second' }) => {
                const cb = (visible: boolean): void => {
                    calls.push({ from: which, visible })
                }
                usePageVisibilityCb(cb)
            },
            { initialProps: { which: 'first' as 'first' | 'second' } }
        )

        expect(calls).toEqual([{ from: 'first', visible: true }])

        rerender({ which: 'second' })

        // Re-render must not fire — even with a new callback identity tagging itself differently.
        expect(calls).toEqual([{ from: 'first', visible: true }])

        // But the next visibility change uses the latest callback.
        act(() => setHidden(true))
        expect(calls).toEqual([
            { from: 'first', visible: true },
            { from: 'second', visible: false },
        ])
    })

    it('usePageVisibilityCb removes the listener on unmount', () => {
        const calls: boolean[] = []
        const { unmount } = renderHook(() => usePageVisibilityCb((v) => calls.push(v)))

        const callsAfterMount = calls.length
        unmount()

        act(() => setHidden(true))
        expect(calls).toHaveLength(callsAfterMount)
    })

    it('usePageVisibility reflects the current visibility', () => {
        const { result } = renderHook(() => usePageVisibility())
        expect(result.current.isVisible).toBe(true)

        act(() => setHidden(true))
        expect(result.current.isVisible).toBe(false)

        act(() => setHidden(false))
        expect(result.current.isVisible).toBe(true)
    })
})
