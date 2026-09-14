import React, { useEffect } from 'react'

/** Runs an effect that intentionally uses values from the initial render only. */
export function useOnMountEffect(effect: React.EffectCallback): void {
    useEffect(effect, []) // oxlint-disable-line react-hooks/exhaustive-deps
}

/**
 * useDelayedOnMountEffect - A hook that runs an effect once on mount, after a specified delay
 *
 * This is similar to useOnMountEffect, but it delays the execution of the effect by the given timeout (default 500ms).
 * It's useful when you want to defer setup logic slightly after mount (e.g., letting initial UI render before firing side effects).
 *
 * Usage:
 * ```tsx
 * useDelayedOnMountEffect(() => {
 *     checkAuth()
 * }, 1000)
 * ```
 *
 * Note: This hook does not run a cleanup callback, use a custom function if you need that behaviour.
 */

export function useDelayedOnMountEffect(effect: () => void, timeout = 500): void {
    useOnMountEffect(() => {
        const timer = window.setTimeout(effect, timeout)
        return () => clearTimeout(timer)
    })
}
