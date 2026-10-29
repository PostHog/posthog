import { act, renderHook } from '@testing-library/react'

import { useHoverIntent } from './useHoverIntent'

describe('useHoverIntent', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        { name: 'a resting pointer', leaveAfterMs: null, calls: 1 },
        { name: 'a pointer that passes over', leaveAfterMs: 50, calls: 0 },
    ])('calls back once for $name', ({ leaveAfterMs, calls }) => {
        const onIntent = jest.fn()
        const { result, unmount } = renderHook(() => useHoverIntent(onIntent, 120))

        act(() => result.current.start())
        if (leaveAfterMs !== null) {
            act(() => jest.advanceTimersByTime(leaveAfterMs))
            act(() => result.current.cancel())
        }
        act(() => jest.advanceTimersByTime(500))
        unmount()

        expect(onIntent).toHaveBeenCalledTimes(calls)
    })
})
