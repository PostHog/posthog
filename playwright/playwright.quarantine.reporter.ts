/**
 * Playwright reporter half of the test quarantine — enforces `mode: "run"`.
 *
 * Playwright has no native non-strict xfail, so a `mode: "run"` quarantined
 * test still executes (keeping its timing/outcome in the html/junit/json
 * reports) and this reporter tolerates a genuine failure: if the ONLY
 * unexpected failures in the run are `mode: "run"` quarantined tests, it
 * overrides the final run status to `passed` so they don't block CI. A single
 * non-quarantined failure keeps the run red.
 *
 * Scope: this only flips the run-level status the CI exit code reads. The
 * per-test outcome in junit-results.xml is written by the separate junit
 * reporter and still records the failure, so a per-test consumer of that file
 * (e.g. test-health ingestion) sees it as failed. Unlike pytest's xfail, the
 * quarantine does not rewrite the per-test result, only the merge gate.
 *
 * The override is deliberately conservative: it fires ONLY when the run's final
 * status is a plain `failed`, no `onError` fired, and every `unexpected` test
 * outcome is covered by a `mode: "run"` entry. Anything surfaced through
 * `onError` (global setup/teardown throw, uncaught error) or a non-`failed`
 * final status (`timedout`, `interrupted`) keeps the run red, because masking a
 * run-level problem would be far worse than a flaky test blocking a merge.
 *
 * Two accepted limitations follow from that conservatism:
 *   - Reaching `--max-failures` both fires `onError` ("Testing stopped early")
 *     and finalizes the run as `interrupted`, so once the cap is hit quarantine
 *     no longer suppresses those failures. That is the safe direction (stay
 *     red) and the alternative (overriding an `onError` run) is not worth it.
 *   - A mid-test worker crash (OOM/segfault) is attributed by Playwright to
 *     that test as `unexpected` rather than through `onError`, so a crash in a
 *     `mode: "run"` test is tolerated as that test's own failure. Playwright
 *     restarts the worker and re-runs the rest, so the blast radius is the
 *     quarantined test itself.
 *
 * `mode: "skip"` is handled earlier by the auto fixture in
 * `utils/playwright-test-core.ts`; skipped tests never reach here as failures.
 *
 * Fail-open: if the quarantine file is missing or unreadable there are no
 * active entries and this reporter is a no-op.
 *
 * Schema contract + matching: `playwright.quarantine.ts` (and core.py behind it).
 */

import type { FullResult, Reporter, Suite, TestCase } from '@playwright/test/reporter'

import { QuarantineDecision, QuarantineEntry, decideForTest, loadActiveEntries } from './playwright.quarantine'

/**
 * Describe titles from the root down, then the test title — the playwright name
 * parts. Anonymous `describe(() => {…})` blocks (empty title) are skipped, so
 * this matches Playwright's own `titlePath()` that the skip fixture consumes via
 * `info.titlePath` — otherwise the two enforcement halves derive different ids.
 */
export function nameParts(test: TestCase): string[] {
    const describes: string[] = []
    for (let suite: Suite | undefined = test.parent; suite && suite.type === 'describe'; suite = suite.parent) {
        if (suite.title) {
            describes.unshift(suite.title)
        }
    }
    return [...describes, test.title]
}

export default class QuarantineReporter implements Reporter {
    private readonly entries: QuarantineEntry[]
    private rootSuite: Suite | undefined
    private sawRunError = false

    // entries is injectable so the onEnd override can be unit-tested without a file.
    constructor(entries: QuarantineEntry[] = loadActiveEntries()) {
        this.entries = entries
    }

    // We only emit occasional warnings, so let Playwright keep its default terminal reporter.
    printsToStdio(): boolean {
        return false
    }

    onBegin(_config: unknown, suite: Suite): void {
        this.rootSuite = suite
    }

    // Errors outside test execution (worker crash, global setup/teardown, uncaught) land here,
    // not as an `unexpected` test — record them so the override below never masks one.
    onError(): void {
        this.sawRunError = true
    }

    async onEnd(result: FullResult): Promise<{ status?: FullResult['status'] } | void> {
        if (this.entries.length === 0 || !this.rootSuite) {
            return
        }
        // Only a plain 'failed' run is a candidate. 'timedout' (global timeout), 'interrupted',
        // and any run-level error are not per-test failures — never override them.
        if (result.status !== 'failed' || this.sawRunError) {
            return
        }

        const tolerated: QuarantineDecision[] = []
        let realFailures = 0
        for (const test of this.rootSuite.allTests()) {
            if (test.outcome() !== 'unexpected') {
                continue // Passed, skipped, or recovered-on-retry (flaky) — not a blocking failure.
            }
            const decision = decideForTest(this.entries, test.location.file, nameParts(test))
            if (decision?.mode === 'run') {
                tolerated.push(decision)
            } else {
                realFailures += 1
            }
        }

        if (tolerated.length === 0) {
            return // Nothing quarantined failed; the run stays red on its own merits.
        }
        for (const decision of tolerated) {
            // eslint-disable-next-line no-console
            console.warn(`[quarantine] tolerated failure in ${decision.label}`)
        }
        if (realFailures > 0) {
            return // Real failures remain — keep the run red.
        }
        // eslint-disable-next-line no-console
        console.warn(
            `[quarantine] overriding run status to passed — the only ${tolerated.length} unexpected ` +
                `failure(s) are quarantined (mode: run)`
        )
        return { status: 'passed' }
    }
}
