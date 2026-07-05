import { act, renderHook } from '@testing-library/react'

import { useVerificationStalled } from './useInstallationComplete'

describe('useVerificationStalled', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.clearAllTimers()
        jest.useRealTimers()
    })

    it('flips to stalled after the delay while still waiting, unblocking the escape hatch', () => {
        const { result } = renderHook(() => useVerificationStalled(false, 30000))

        expect(result.current).toBe(false)

        act(() => jest.advanceTimersByTime(29999))
        expect(result.current).toBe(false)

        act(() => jest.advanceTimersByTime(1))
        expect(result.current).toBe(true)
    })

    it('never stalls once installation completes before the delay', () => {
        const { result, rerender } = renderHook(({ complete }) => useVerificationStalled(complete, 30000), {
            initialProps: { complete: false },
        })

        act(() => jest.advanceTimersByTime(10000))
        expect(result.current).toBe(false)

        rerender({ complete: true })
        act(() => jest.advanceTimersByTime(30000))
        expect(result.current).toBe(false)
    })
})
