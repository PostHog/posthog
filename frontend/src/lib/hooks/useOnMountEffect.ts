import React, { useEffect } from 'react'

/**
 * useOnMountEffect - A hook that runs an effect only once when the component mounts
 *
 * This is a wrapper around useEffect with an empty dependency array, making the intent
 * explicit that the effect should only run once on mount. This pattern is common enough
 * that having a dedicated hook improves code readability and intent.
 *
 * Why this exists:
 * - Makes the "run once on mount" intent explicit in the function name
 * - Avoids repetitive empty dependency arrays throughout the codebase
 * - Centralizes the oxlint disable comment for the exhaustive-deps rule
 *
 * Usage:
 * ```tsx
 * useOnMountEffect(() => {
 *     // This code runs only once when component mounts
 *     fetchData()
 *     setupEventListeners()
 *
 *     return () => {
 *         // Cleanup code (optional)
 *         removeEventListeners()
 *     }
 * })
 * ```
 *
 * Note: The oxlint disable is intentional - we specifically want an empty dependency
 * array here to ensure the effect only runs once on mount, despite what the
 * exhaustive-deps rule suggests.
 */
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
