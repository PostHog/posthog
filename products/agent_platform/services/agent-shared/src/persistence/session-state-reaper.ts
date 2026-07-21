/**
 * Classifies the reaper for every `SessionState` — the process that moves a state
 * forward even if the holder dies, so a session can't wedge. Keying the `Record`
 * on the union makes a new state a compile error until it's classified.
 *
 * `final` differs from `queue.ts`'s "terminal" (= not live): `completed` is not
 * live yet not final (the sweep closes it), so it's `sweep-closes`.
 *
 *   final          — lifecycle-final (closed/cancelled/failed); no reaper needed.
 *   worker-claims  — a runner Worker claims it off the queue and advances it.
 *   sweep-requeues — janitor sweep re-queues it if the worker died holding it.
 *   sweep-closes   — janitor sweep advances it to a final state when idle.
 */
import type { SessionState } from '../spec/spec'

export type ReaperKind = 'final' | 'worker-claims' | 'sweep-requeues' | 'sweep-closes'

export const SESSION_STATE_REAPER: Record<SessionState, ReaperKind> = {
    queued: 'worker-claims',
    running: 'sweep-requeues',
    completed: 'sweep-closes',
    closed: 'final',
    cancelled: 'final',
    failed: 'final',
}

export function isFinalSessionState(s: SessionState): boolean {
    return SESSION_STATE_REAPER[s] === 'final'
}
