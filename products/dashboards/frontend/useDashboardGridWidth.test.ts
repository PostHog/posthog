import { act, renderHook } from '@testing-library/react'

import { useDashboardGridWidth } from './useDashboardGridWidth'

describe('useDashboardGridWidth', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    it.each([
        { name: 'the same width after a zero measurement', widths: [0, 1200], expected: [1200, 1200] },
        { name: 'a different width after a zero measurement', widths: [0, 1000], expected: [1200, 1000] },
        {
            name: 'a breakpoint crossing after a zero measurement',
            widths: [0, 600, 0, 1000],
            expected: [1200, 600, 600, 1000],
        },
    ])('keeps $name', ({ widths, expected }) => {
        const { result, rerender } = renderHook(({ width }) => useDashboardGridWidth(width), {
            initialProps: { width: 1200 },
        })
        for (const [index, width] of widths.entries()) {
            const previous = result.current
            rerender({ width })
            expect(result.current).toBe(previous)
            act(() => jest.advanceTimersByTime(100))
            expect(result.current).toBe(expected[index])
        }
    })
})
