import { useEffect, useState } from 'react'

/**
 * Returns a debounced version of the given value. Truthy transitions are
 * delayed by `delayMs`; falsy transitions are applied immediately.
 * Useful for delaying the appearance of loading indicators.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
    const [debounced, setDebounced] = useState(value)
    useEffect(() => {
        if (value) {
            const timer = setTimeout(() => setDebounced(value), delayMs)
            return () => clearTimeout(timer)
        }
        setDebounced(value)
    }, [value, delayMs])
    return debounced
}
