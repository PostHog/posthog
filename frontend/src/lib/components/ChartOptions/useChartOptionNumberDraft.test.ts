import { act, renderHook } from '@testing-library/react'

import { useChartOptionNumberDraft } from './useChartOptionNumberDraft'

describe('useChartOptionNumberDraft', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('drops a queued value when the field is cleared before it sends', () => {
        const onChange = jest.fn()
        const { result } = renderHook(() => useChartOptionNumberDraft(40, onChange))

        act(() => result.current.setDraft('55'))
        act(() => result.current.setDraft(''))
        act(() => jest.advanceTimersByTime(1000))
        expect(onChange).not.toHaveBeenCalled()

        act(() => result.current.commit())
        expect(onChange).toHaveBeenCalledWith(undefined)
    })

    it('keeps newer typing when an older save arrives', () => {
        const onChange = jest.fn()
        const { result, rerender } = renderHook(({ value }) => useChartOptionNumberDraft(value, onChange), {
            initialProps: { value: undefined as number | undefined },
        })

        act(() => result.current.setDraft('1'))
        act(() => jest.advanceTimersByTime(300))
        act(() => result.current.setDraft('12'))
        rerender({ value: 1 })
        expect(result.current.draft).toBe('12')

        act(() => result.current.commit())
        expect(onChange).toHaveBeenLastCalledWith(12)
    })

    it('keeps a lone minus sign so a negative value can be typed', () => {
        const onChange = jest.fn()
        const { result } = renderHook(() => useChartOptionNumberDraft(undefined, onChange))

        act(() => result.current.setDraft('-'))
        expect(result.current.draft).toBe('-')

        act(() => result.current.setDraft('-10'))
        act(() => jest.advanceTimersByTime(1000))
        expect(onChange).toHaveBeenLastCalledWith(-10)
    })
})
