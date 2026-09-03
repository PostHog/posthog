import { act, renderHook } from '@testing-library/react'

import { LINGERING_TOOLTIP_MS, useLingeringTooltip } from './useLingeringTooltip'

describe('useLingeringTooltip', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('passes the chart visibility straight through when disabled', () => {
        const { result, rerender } = renderHook(({ chartVisible }) => useLingeringTooltip(chartVisible, false), {
            initialProps: { chartVisible: true },
        })
        expect(result.current.visible).toBe(true)

        rerender({ chartVisible: false })
        expect(result.current.visible).toBe(false)
    })

    it('lingers after the chart hides so the pointer can reach the tooltip, then hides', () => {
        const { result, rerender } = renderHook(({ chartVisible }) => useLingeringTooltip(chartVisible, true), {
            initialProps: { chartVisible: true },
        })
        expect(result.current.visible).toBe(true)

        rerender({ chartVisible: false })
        // Still up — this window is the whole point: without it the pointer never arrives.
        expect(result.current.visible).toBe(true)

        act(() => {
            jest.advanceTimersByTime(LINGERING_TOOLTIP_MS)
        })
        expect(result.current.visible).toBe(false)
    })

    it('holds the tooltip open indefinitely while the pointer is over it', () => {
        const { result, rerender } = renderHook(({ chartVisible }) => useLingeringTooltip(chartVisible, true), {
            initialProps: { chartVisible: true },
        })

        rerender({ chartVisible: false })
        act(() => {
            result.current.onMouseEnter()
        })

        act(() => {
            jest.advanceTimersByTime(LINGERING_TOOLTIP_MS * 20)
        })
        expect(result.current.visible).toBe(true)
    })

    it('hides once the pointer leaves the tooltip', () => {
        const { result, rerender } = renderHook(({ chartVisible }) => useLingeringTooltip(chartVisible, true), {
            initialProps: { chartVisible: true },
        })

        rerender({ chartVisible: false })
        act(() => {
            result.current.onMouseEnter()
        })
        act(() => {
            jest.advanceTimersByTime(LINGERING_TOOLTIP_MS * 5)
        })
        expect(result.current.visible).toBe(true)

        act(() => {
            result.current.onMouseLeave()
        })
        act(() => {
            jest.advanceTimersByTime(LINGERING_TOOLTIP_MS)
        })
        expect(result.current.visible).toBe(false)
    })

    it('re-shows immediately when the pointer returns to the chart mid-linger', () => {
        const { result, rerender } = renderHook(({ chartVisible }) => useLingeringTooltip(chartVisible, true), {
            initialProps: { chartVisible: true },
        })

        rerender({ chartVisible: false })
        rerender({ chartVisible: true })
        act(() => {
            jest.advanceTimersByTime(LINGERING_TOOLTIP_MS * 3)
        })
        expect(result.current.visible).toBe(true)
    })

    it('does not stay wedged open when the behaviour is disabled mid-hover', () => {
        const { result, rerender } = renderHook(
            ({ chartVisible, enabled }) => useLingeringTooltip(chartVisible, enabled),
            { initialProps: { chartVisible: true, enabled: true } }
        )

        rerender({ chartVisible: false, enabled: true })
        act(() => {
            result.current.onMouseEnter()
        })
        expect(result.current.visible).toBe(true)

        rerender({ chartVisible: false, enabled: false })
        expect(result.current.visible).toBe(false)
    })
})
