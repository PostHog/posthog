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
