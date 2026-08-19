// @ts-nocheck
// Test fixture for the useeffect-callback-returns-non-function rule.
import { useEffect } from 'react'

export function BadCases(): null {
    // A bound kea action returns the action object, not a cleanup function.
    // ruleid: useeffect-callback-returns-non-function
    useEffect(() => loadKeys(), [loadKeys])

    // A useState setter returns undefined, so this is safe by accident.
    // ruleid: useeffect-callback-returns-non-function
    useEffect(() => setValue(1), [value])

    // Method call, same footgun.
    // ruleid: useeffect-callback-returns-non-function
    useEffect(() => obj.method(), [])

    // Inline `return call()` still stores the result as the cleanup.
    // ruleid: useeffect-callback-returns-non-function
    useEffect(() => {
        return subscribe()
    }, [])

    return null
}

export function OkCases(): null {
    // ok: useeffect-callback-returns-non-function
    useEffect(() => {
        loadKeys()
    }, [loadKeys])

    // ok: useeffect-callback-returns-non-function
    useEffect(() => {
        const cleanup = subscribe()
        return cleanup
    }, [])

    // ok: useeffect-callback-returns-non-function
    useEffect(() => () => cleanup(), [])

    // ok: useeffect-callback-returns-non-function
    useEffect(() => cleanupRef, [cleanupRef])

    return null
}
