import { act, renderHook } from '@testing-library/react'
import { useInView } from 'react-intersection-observer'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'

import { AUTO_MARK_READ_DWELL_MS, useAutoMarkRead } from './useAutoMarkRead'

jest.mock('react-intersection-observer', () => ({ useInView: jest.fn() }))
jest.mock('lib/hooks/usePageVisibility', () => ({ usePageVisibility: jest.fn() }))

const mockUseInView = useInView as jest.Mock
const mockUsePageVisibility = usePageVisibility as jest.Mock

describe('useAutoMarkRead', () => {
    let inView: boolean
    let pageVisible: boolean

    beforeEach(() => {
        jest.useFakeTimers()
        inView = true
        pageVisible = true
        mockUseInView.mockImplementation(() => ({ ref: jest.fn(), inView }))
        mockUsePageVisibility.mockImplementation(() => ({ isVisible: pageVisible }))
    })

    afterEach(() => {
        jest.clearAllTimers()
        jest.useRealTimers()
    })

    it('fires once after an uninterrupted dwell', () => {
        const onDwell = jest.fn()
        renderHook(() => useAutoMarkRead(true, onDwell))

        expect(onDwell).not.toHaveBeenCalled()
        act(() => jest.advanceTimersByTime(AUTO_MARK_READ_DWELL_MS))
        expect(onDwell).toHaveBeenCalledTimes(1)

        // Staying visible past the dwell does not fire again.
        act(() => jest.advanceTimersByTime(AUTO_MARK_READ_DWELL_MS * 2))
        expect(onDwell).toHaveBeenCalledTimes(1)
    })

    it('does not fire if the item leaves the viewport before the dwell elapses', () => {
        const onDwell = jest.fn()
        const { rerender } = renderHook(() => useAutoMarkRead(true, onDwell))

        act(() => jest.advanceTimersByTime(AUTO_MARK_READ_DWELL_MS - 500))
        inView = false
        rerender()
        act(() => jest.advanceTimersByTime(AUTO_MARK_READ_DWELL_MS))

        expect(onDwell).not.toHaveBeenCalled()
    })

    it('restarts the dwell after the item re-enters the viewport', () => {
        const onDwell = jest.fn()
        const { rerender } = renderHook(() => useAutoMarkRead(true, onDwell))

        act(() => jest.advanceTimersByTime(AUTO_MARK_READ_DWELL_MS - 500))
        inView = false
        rerender()
        act(() => jest.advanceTimersByTime(1000))
        inView = true
        rerender()

        // Only a partial dwell so far — still nothing.
        act(() => jest.advanceTimersByTime(AUTO_MARK_READ_DWELL_MS - 500))
        expect(onDwell).not.toHaveBeenCalled()
        act(() => jest.advanceTimersByTime(500))
        expect(onDwell).toHaveBeenCalledTimes(1)
    })

    it('does not count time while the browser tab is hidden', () => {
        const onDwell = jest.fn()
        pageVisible = false
        const { rerender } = renderHook(() => useAutoMarkRead(true, onDwell))

        act(() => jest.advanceTimersByTime(AUTO_MARK_READ_DWELL_MS * 2))
        expect(onDwell).not.toHaveBeenCalled()

        pageVisible = true
        rerender()
        act(() => jest.advanceTimersByTime(AUTO_MARK_READ_DWELL_MS))
        expect(onDwell).toHaveBeenCalledTimes(1)
    })

    it('never fires for an inactive (already read) item', () => {
        const onDwell = jest.fn()
        renderHook(() => useAutoMarkRead(false, onDwell))

        act(() => jest.advanceTimersByTime(AUTO_MARK_READ_DWELL_MS * 2))
        expect(onDwell).not.toHaveBeenCalled()
    })
})
