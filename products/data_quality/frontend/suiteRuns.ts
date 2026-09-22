import { pluralize } from 'lib/utils/strings'

import type { DataQualityCheckRunApi, DataQualitySuiteRunApi } from './generated/api.schemas'

const TERMINAL_SUITE_RUN_STATUSES = ['completed', 'failed', 'empty']
const FAST_POLL_INTERVAL_MS = 3000
const SLOW_POLL_INTERVAL_MS = 15000
const FAST_POLL_WINDOW_MS = 60_000

/** How long a run may stay 'running' before the UI stops asking and offers a manual refresh. */
export const POLL_TIMEOUT_MS = 15 * 60_000

export function isTerminalSuiteRun(suiteRun: DataQualitySuiteRunApi | null): boolean {
    return !!suiteRun && TERMINAL_SUITE_RUN_STATUSES.includes(suiteRun.status)
}

/** Tight while a run is likely to finish, then backed off so a long one costs little. */
export function pollDelayMs(elapsedMs: number): number {
    return elapsedMs < FAST_POLL_WINDOW_MS ? FAST_POLL_INTERVAL_MS : SLOW_POLL_INTERVAL_MS
}

/** The newest run that still has its query. Retention clears the compiled query after 30 days. */
export function latestFailingRowsQuery(runs: DataQualityCheckRunApi[]): string | null {
    return runs.find((run) => run.compiled_query)?.compiled_query || null
}

export type SuiteRunOutcome = 'empty' | 'errored' | 'warning' | 'success'

/** What a finished run amounts to. A 'failed' suite that failed no check errored on its own way in. */
export function suiteRunOutcome(suiteRun: DataQualitySuiteRunApi): SuiteRunOutcome {
    if (suiteRun.status === 'empty') {
        return 'empty'
    }
    if (suiteRun.status === 'failed' && !suiteRun.checks_failed) {
        return 'errored'
    }
    return suiteRun.checks_failed || suiteRun.checks_errored ? 'warning' : 'success'
}

interface SuiteRunPollCache {
    pollElapsedMs: number
    disposables: {
        add: (create: () => () => void, key: string) => void
        dispose: (key: string) => void
        isDisposed: boolean
    }
}

interface SuiteRunPollActions {
    finishSuiteRun: (suiteRun: DataQualitySuiteRunApi) => unknown
    scheduleSuiteRunPoll: () => unknown
    pollActiveSuiteRun: () => unknown
    setPollTimedOut: () => unknown
}

interface SuiteRunPollListeners {
    setActiveSuiteRun: (payload: { suiteRun: DataQualitySuiteRunApi | null }) => void
    scheduleSuiteRunPoll: () => void
    pollActiveSuiteRun: () => Promise<void>
}

/**
 * The three listeners that drive a suite run to its terminal state, for a logic that supplies its
 * own retrieve. Both surfaces poll the same way against different endpoints, so the schedule, the
 * backoff and the timeout live here rather than in each logic.
 */
export function suiteRunPollListeners({
    retrieve,
    onPollError,
    cache: untypedCache,
    values,
    actions,
}: {
    retrieve: (suiteRunId: string) => Promise<DataQualitySuiteRunApi>
    /** Handle a surface-specific failure. Return true to stop polling instead of retrying. */
    onPollError?: (error: unknown) => boolean
    // kea types `cache` as Record<string, any>, so the shape this needs is asserted once here
    // rather than at both call sites.
    cache: Record<string, any>
    values: { activeSuiteRun: DataQualitySuiteRunApi | null }
    actions: SuiteRunPollActions
}): SuiteRunPollListeners {
    const cache = untypedCache as SuiteRunPollCache
    return {
        setActiveSuiteRun: ({ suiteRun }: { suiteRun: DataQualitySuiteRunApi | null }): void => {
            cache.disposables.dispose('suiteRunPoll')
            cache.pollElapsedMs = 0
            if (!suiteRun) {
                return
            }
            if (isTerminalSuiteRun(suiteRun)) {
                actions.finishSuiteRun(suiteRun)
                return
            }
            actions.scheduleSuiteRunPoll()
        },
        scheduleSuiteRunPoll: (): void => {
            const delay = pollDelayMs(cache.pollElapsedMs)
            cache.disposables.add(() => {
                const timeoutId = setTimeout(() => {
                    cache.pollElapsedMs += delay
                    actions.pollActiveSuiteRun()
                }, delay)
                return () => clearTimeout(timeoutId)
            }, 'suiteRunPoll')
        },
        pollActiveSuiteRun: async (): Promise<void> => {
            const running = values.activeSuiteRun
            if (!running) {
                return
            }
            let polled: DataQualitySuiteRunApi
            try {
                polled = await retrieve(running.id)
            } catch (error) {
                if (onPollError?.(error)) {
                    return
                }
                // Other failures are transient and not worth a toast, but they still count toward the
                // cap, so a request that keeps failing stops rather than retrying forever.
                if (cache.pollElapsedMs >= POLL_TIMEOUT_MS) {
                    actions.setPollTimedOut()
                    return
                }
                actions.scheduleSuiteRunPoll()
                return
            }
            // A newer run may have started while this retrieve was in flight. A stale terminal
            // response would otherwise finish the old run and dispose the newer run's poll.
            if (cache.disposables.isDisposed || values.activeSuiteRun?.id !== running.id) {
                return
            }
            if (isTerminalSuiteRun(polled)) {
                actions.finishSuiteRun(polled)
                return
            }
            if (cache.pollElapsedMs >= POLL_TIMEOUT_MS) {
                actions.setPollTimedOut()
                return
            }
            actions.scheduleSuiteRunPoll()
        },
    }
}

export function suiteRunSummary(suiteRun: DataQualitySuiteRunApi): string {
    const outcomes: [number, string][] = [
        [suiteRun.checks_passed, 'passed'],
        [suiteRun.checks_failed, 'failed'],
        [suiteRun.checks_errored, 'errored'],
        [suiteRun.checks_skipped, 'skipped'],
    ]
    if (suiteRun.checks_failed === 0 && suiteRun.checks_errored === 0 && suiteRun.checks_passed > 0) {
        return `All ${pluralize(suiteRun.checks_passed, 'check')} passed`
    }
    return outcomes
        .filter(([count]) => count > 0)
        .map(([count, outcome]) => `${count} ${outcome}`)
        .join(', ')
}
