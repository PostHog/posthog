import { useEffect, useState } from 'react'

/**
 * Returns a debounced copy of `value` that updates after `delayMs` of stability.
 * Falsy values propagate immediately so loading-style flags can be cleared without delay.
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
