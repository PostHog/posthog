import type { FullResult, Suite, TestCase } from '@playwright/test/reporter'
import * as path from 'path'

import { QuarantineEntry, REPO_ROOT } from '../../../playwright/playwright.quarantine'
import QuarantineReporter, { nameParts } from '../../../playwright/playwright.quarantine.reporter'

// The reporter's onEnd can flip a red run to passed, so it is the highest-risk
// code here and needs its own lock: these cover when it tolerates, when it must
// keep the run red, and that the run-half id agrees with the skip fixture.

type FakeSuite = { type: string; title: string; parent?: FakeSuite }
type Outcome = ReturnType<TestCase['outcome']>

function fakeTest(relFile: string, describes: string[], title: string, outcome: Outcome): TestCase {
    const fileSuite: FakeSuite = { type: 'file', title: relFile }
    let parent: FakeSuite = fileSuite
    for (const describe of describes) {
        parent = { type: 'describe', title: describe, parent }
    }
    return {
        title,
        outcome: () => outcome,
        location: { file: path.join(REPO_ROOT, relFile) },
        parent,
    } as unknown as TestCase
}

function runEntry(id: string): QuarantineEntry {
    return { id, mode: 'run', reason: 'flaky', owner: '@web', issue: '', expires: '2026-12-31' }
}

function reporterFor(entries: QuarantineEntry[], tests: TestCase[]): QuarantineReporter {
    const reporter = new QuarantineReporter(entries)
    reporter.onBegin({}, { allTests: () => tests } as unknown as Suite)
    return reporter
}

const failedRun = { status: 'failed' } as unknown as FullResult

describe('playwright.quarantine.reporter', () => {
    let warn: jest.SpyInstance

    beforeEach(() => {
        warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined)
    })
    afterEach(() => {
        warn.mockRestore()
    })

    test('overrides a failed run to passed when every unexpected failure is a mode:run quarantined test', async () => {
        const tests = [
            fakeTest('playwright/e2e/x.spec.ts', ['Auth'], 'logs in', 'unexpected'),
            fakeTest('playwright/e2e/y.spec.ts', [], 'passes', 'expected'),
        ]
        const reporter = reporterFor([runEntry('playwright/e2e/x.spec.ts::Auth logs in')], tests)
        expect(await reporter.onEnd(failedRun)).toEqual({ status: 'passed' })
    })

    test('keeps the run red when a non-quarantined test also failed', async () => {
        const tests = [
            fakeTest('playwright/e2e/x.spec.ts', ['Auth'], 'logs in', 'unexpected'),
            fakeTest('playwright/e2e/z.spec.ts', [], 'real regression', 'unexpected'),
        ]
        const reporter = reporterFor([runEntry('playwright/e2e/x.spec.ts::Auth logs in')], tests)
        expect(await reporter.onEnd(failedRun)).toBeUndefined()
    })

    test('never overrides once a run-level error fired (onError)', async () => {
        const tests = [fakeTest('playwright/e2e/x.spec.ts', ['Auth'], 'logs in', 'unexpected')]
        const reporter = reporterFor([runEntry('playwright/e2e/x.spec.ts::Auth logs in')], tests)
        reporter.onError()
        expect(await reporter.onEnd(failedRun)).toBeUndefined()
    })

    test('only a failed final status is a candidate — interrupted stays red', async () => {
        const tests = [fakeTest('playwright/e2e/x.spec.ts', ['Auth'], 'logs in', 'unexpected')]
        const reporter = reporterFor([runEntry('playwright/e2e/x.spec.ts::Auth logs in')], tests)
        expect(await reporter.onEnd({ status: 'interrupted' } as unknown as FullResult)).toBeUndefined()
    })

    test('a mode:run entry matches a test in an anonymous describe (reporter id omits the empty title)', async () => {
        // The skip fixture derives ids from Playwright titlePath, which drops anonymous
        // describes; nameParts must agree or the run half silently fails to match.
        const anon = fakeTest('playwright/e2e/x.spec.ts', [''], 'loads', 'unexpected')
        expect(nameParts(anon)).toEqual(['loads'])
        const reporter = reporterFor([runEntry('playwright/e2e/x.spec.ts::loads')], [anon])
        expect(await reporter.onEnd(failedRun)).toEqual({ status: 'passed' })
    })

    test('no active entries makes the reporter a no-op', async () => {
        const tests = [fakeTest('playwright/e2e/x.spec.ts', ['Auth'], 'logs in', 'unexpected')]
        const reporter = reporterFor([], tests)
        expect(await reporter.onEnd(failedRun)).toBeUndefined()
    })
})
