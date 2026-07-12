import { ApiError } from 'lib/api-error'

// How a wizard sync stream pulls updates. `sse` holds a live EventSource; `polling` re-fetches a REST
// snapshot on an interval (GROW-118). Toggled by the `onboarding-wizard-sync-mode` flag; `sse` stays
// the default when the flag is off or unset.
export type WizardSyncMode = 'sse' | 'polling'

export function resolveWizardSyncMode(flagValue: unknown): WizardSyncMode {
    return flagValue === 'polling' ? 'polling' : 'sse'
}

export const DEFAULT_POLLING_INTERVAL_SECS = 3
const MIN_POLLING_INTERVAL_SECS = 1
// Also guards against `window.setTimeout` int32 overflow: a delay above 2^31-1 ms fires immediately,
// which would turn a fat-fingered payload into a tight polling loop across every flagged client.
export const MAX_POLLING_INTERVAL_SECS = 300

// Resolve the poll cadence from the flag payload's `polling_interval_secs`, falling back to the default
// and clamping on both ends so a stray payload can neither hammer the endpoint nor stall sync entirely.
export function resolvePollingIntervalMs(payload: unknown): number {
    const raw = (payload as { polling_interval_secs?: unknown } | null)?.polling_interval_secs
    const secs = typeof raw === 'number' && Number.isFinite(raw) ? raw : DEFAULT_POLLING_INTERVAL_SECS
    return Math.min(MAX_POLLING_INTERVAL_SECS, Math.max(MIN_POLLING_INTERVAL_SECS, secs)) * 1000
}

// Spread poll ticks ±20% around the base cadence so clients whose runs kicked off together (or whose
// tabs woke together) don't hit the endpoint in lockstep, avoiding a thundering herd on the API.
export const POLL_JITTER_RATIO = 0.2
export function jitteredIntervalMs(baseMs: number, random: () => number = Math.random): number {
    return Math.round(baseMs * (1 - POLL_JITTER_RATIO + random() * 2 * POLL_JITTER_RATIO))
}

// Backoff ceiling for consecutive failures/empties, and how many empty ticks ride the base cadence
// before slowing down (a run usually appears within a few ticks; a killswitched or idle endpoint
// should not be polled at full rate forever).
export const MAX_POLL_BACKOFF_MS = 60_000
export const EMPTY_POLLS_BEFORE_BACKOFF = 5

// 401/403 (access revoked), 404 (deleted), 410 (gone): retrying cannot succeed, stop the loop.
export function isPermanentPollError(error: unknown): boolean {
    return error instanceof ApiError && [401, 403, 404, 410].includes(error.status ?? 0)
}

export type PollTickOutcome = 'ok' | 'empty' | 'terminal'

export interface PollLoopOptions {
    /** Base cadence between ticks; jitter and backoff are applied on top. */
    intervalMs: number
    /** Fetch + dispatch one snapshot. Classify the result; throw on request failure. */
    tick: () => Promise<PollTickOutcome>
    /** Called for each failed tick. Return 'stop' to end the loop permanently. */
    onError: (error: unknown, consecutiveFailures: number) => 'retry' | 'stop'
    /** Checked before each tick; returning true ends the loop permanently. */
    shouldStop?: () => boolean
    /** Runs when the loop ends itself (terminal tick, error stop, shouldStop) — not on external cleanup. */
    onLoopEnd?: () => void
}

/**
 * Shared poll loop for the wizard sync transports (task-run and wizard-session polling modes).
 * Returns a disposable setup function for `cache.disposables.add`.
 *
 * Guarantees:
 * - Each tick schedules the next one only after its request settles, so a slow server can never
 *   stack requests, and every gap gets fresh jitter.
 * - Consecutive failures back off exponentially (capped at MAX_POLL_BACKOFF_MS) and permanent
 *   errors stop the loop, so an outage or a deleted resource is not hammered at full cadence.
 * - Consecutive empty ticks past EMPTY_POLLS_BEFORE_BACKOFF back off the same way, so an endpoint
 *   with nothing to report (no session yet, killswitched) winds down instead of polling forever.
 */
export function createPollLoop(options: PollLoopOptions): () => () => void {
    return (): (() => void) => {
        let cancelled = false
        let timer: number | undefined
        let consecutiveFailures = 0
        let consecutiveEmpty = 0

        const nextDelayMs = (): number => {
            if (consecutiveFailures > 0) {
                return Math.min(options.intervalMs * 2 ** consecutiveFailures, MAX_POLL_BACKOFF_MS)
            }
            const emptyOverage = consecutiveEmpty - EMPTY_POLLS_BEFORE_BACKOFF
            if (emptyOverage >= 0) {
                return Math.min(options.intervalMs * 2 ** (emptyOverage + 1), MAX_POLL_BACKOFF_MS)
            }
            return options.intervalMs
        }

        const poll = async (): Promise<void> => {
            // Re-checked every tick, not just at connect: the disposables plugin re-runs setup on
            // tab-visibility resume, so connect-time guards alone would let a stale loop revive.
            if (options.shouldStop?.()) {
                options.onLoopEnd?.()
                return
            }
            try {
                const outcome = await options.tick()
                if (cancelled) {
                    return
                }
                consecutiveFailures = 0
                consecutiveEmpty = outcome === 'empty' ? consecutiveEmpty + 1 : 0
                if (outcome === 'terminal') {
                    options.onLoopEnd?.()
                    return
                }
            } catch (error) {
                if (cancelled) {
                    return
                }
                consecutiveFailures += 1
                if (options.onError(error, consecutiveFailures) === 'stop') {
                    options.onLoopEnd?.()
                    return
                }
            }
            // A tick's dispatches can synchronously dispose this loop; don't schedule an orphan.
            if (!cancelled) {
                timer = window.setTimeout(() => void poll(), jitteredIntervalMs(nextDelayMs()))
            }
        }
        void poll()
        return () => {
            cancelled = true
            window.clearTimeout(timer)
        }
    }
}
