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
