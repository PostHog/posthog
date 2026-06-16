/**
 * Global "anything in flight?" counter.
 *
 * Every `useResource` call wraps its factory's promise in `trackInFlight`
 * so the count goes up when a fetch starts and down when it
 * resolves/rejects. The top-of-viewport progress bar in `AppShell`
 * subscribes via `useInFlightCount()` and animates whenever count > 0.
 *
 * Module-level / mutable for the same reasons as `reloadSignal` — there's
 * only ever one tab, and it's a UI-only signal.
 */

'use client'

import { useEffect, useState } from 'react'

let inFlight = 0
const listeners = new Set<() => void>()

function notify(): void {
    for (const l of listeners) {
        try {
            l()
        } catch {
            // Listener bug — skip so others still fire.
        }
    }
}

/**
 * Increment the counter, return a `done()` that decrements once (idempotent).
 * Callers pair it with a `try / finally` around the awaited promise.
 */
export function startInFlight(): () => void {
    inFlight += 1
    notify()
    let released = false
    return (): void => {
        if (released) {
            return
        }
        released = true
        inFlight = Math.max(0, inFlight - 1)
        notify()
    }
}

/** Convenience wrapper: track a promise from start → settle. */
export async function trackInFlight<T>(p: Promise<T>): Promise<T> {
    const done = startInFlight()
    try {
        return await p
    } finally {
        done()
    }
}

export function useInFlightCount(): number {
    const [n, setN] = useState(inFlight)
    useEffect(() => {
        const sub = (): void => setN(inFlight)
        listeners.add(sub)
        return () => {
            listeners.delete(sub)
        }
    }, [])
    return n
}
