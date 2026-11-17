import { act, renderHook } from '@testing-library/react'

import { useDebouncedValue } from './useDebouncedValue'

describe('useDebouncedValue', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        { name: 'returns a value that is truthy on mount at once', initialValue: undefined, onMount: true },
        {
            name: 'delays a value that is truthy on mount when initialValue is false',
            initialValue: false,
            onMount: false,
        },
    ])('$name', ({ initialValue, onMount }) => {
        const { result } = renderHook(() =>
            initialValue === undefined ? useDebouncedValue(true, 200) : useDebouncedValue(true, 200, initialValue)
        )

        expect(result.current).toBe(onMount)

        act(() => jest.advanceTimersByTime(200))
        expect(result.current).toBe(true)
    })

    it('delays a truthy change and applies a falsy change at once', () => {
        const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 200, false), {
            initialProps: { value: false },
        })

        rerender({ value: true })
        act(() => jest.advanceTimersByTime(199))
        expect(result.current).toBe(false)

        act(() => jest.advanceTimersByTime(1))
        expect(result.current).toBe(true)

        rerender({ value: false })
        expect(result.current).toBe(false)
    })
})
