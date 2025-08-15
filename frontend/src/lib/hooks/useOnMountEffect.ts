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

export function useDelayedOnMountEffect(effect: React.EffectCallback, timeout = 500): void {
    useEffect(() => {
        window.setTimeout(effect, timeout)
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps
}
