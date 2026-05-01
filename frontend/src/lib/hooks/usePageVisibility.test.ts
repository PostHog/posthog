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
