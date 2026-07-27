import { describe, expect, it } from 'vitest'

import { LIVE_SESSION_STATES } from './queue'
import { isFinalSessionState, SESSION_STATE_REAPER } from './session-state-reaper'

/**
 * Cross-checks the compile-time classification against `queue.ts`: a state the
 * queue considers LIVE must have a forward path (never `final`, else it wedges),
 * and the `final` set is exactly the lifecycle-final states.
 */
describe('session-state reaper classification', () => {
    it('every live state (per queue.ts) has a forward path, never final', () => {
        const wrongly_final = LIVE_SESSION_STATES.filter((s) => SESSION_STATE_REAPER[s] === 'final')
        expect(wrongly_final, `live states marked final (would wedge): ${wrongly_final.join(', ')}`).toEqual([])
    })

    it('final states are exactly the lifecycle-final states', () => {
        const final = (Object.keys(SESSION_STATE_REAPER) as (keyof typeof SESSION_STATE_REAPER)[])
            .filter((s) => isFinalSessionState(s))
            .sort()
        expect(final).toEqual(['cancelled', 'closed', 'failed'])
    })

    it('completed is reaped, not final (open-but-idle → swept closed)', () => {
        // The exact disagreement guarded against: queue.ts counts `completed` as
        // not-live, but it must NOT be final here — the sweep still closes it.
        expect(isFinalSessionState('completed')).toBe(false)
        expect(SESSION_STATE_REAPER.completed).toBe('sweep-closes')
    })
})
