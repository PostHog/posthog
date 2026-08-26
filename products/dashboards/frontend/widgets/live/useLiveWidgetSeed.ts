import { useEffect } from 'react'

import type { LiveWidgetSeedPayload } from './liveWidgetTypes'

/**
 * Bridges a live widget's run_widgets `result` prop into its logic's seed action.
 *
 * This is the one accepted prop→action React bridge for live widgets: the seed arrives as a React
 * prop from the platform tile renderer, so the handoff has to happen in React. Seeding is safe to
 * repeat (seed merges are idempotent by contract), so re-renders and re-fetches need no guarding
 * beyond payload identity — pass `null` while the payload isn't ready.
 */
export function useLiveWidgetSeed<P extends LiveWidgetSeedPayload>(
    payload: P | null,
    seed: (payload: P) => void
): void {
    useEffect(() => {
        if (payload) {
            seed(payload)
        }
    }, [payload, seed])
}
