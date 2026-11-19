import { useEffect, useState } from 'react'

/**
 * Returns a debounced version of the given value. Truthy transitions are
 * delayed by `delayMs`; falsy transitions are applied immediately.
 * Useful for delaying the appearance of loading indicators.
 * Pass `initialValue` (such as `false`) so a value that is truthy on mount is also delayed.
 */
export function useDebouncedValue<T>(value: T, delayMs: number, initialValue: T = value): T {
    const [debounced, setDebounced] = useState(initialValue)
    useEffect(() => {
        if (value) {
            const timer = setTimeout(() => setDebounced(value), delayMs)
            return () => clearTimeout(timer)
        }
        setDebounced(value)
    }, [value, delayMs])
    return debounced
}
