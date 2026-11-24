import type { DataQualitySuiteRunApi } from './generated/api.schemas'
import { suiteRunToastMessage } from './suiteRuns'

function buildSuiteRun(overrides: Partial<DataQualitySuiteRunApi> = {}): DataQualitySuiteRunApi {
    return {
        id: 'suite-1',
        status: 'completed',
        trigger: 'manual',
        checks_passed: 0,
        checks_failed: 0,
        checks_errored: 0,
        checks_skipped: 0,
        error: '',
        ...overrides,
    } as DataQualitySuiteRunApi
}

describe('suiteRuns', () => {
    it.each<[string, Partial<DataQualitySuiteRunApi>, string]>([
        ['all passed', { checks_passed: 7 }, 'All 7\u00a0data quality checks passed'],
        [
            'large counts',
            { checks_passed: 100000, checks_failed: 12345, checks_errored: 10000 },
            "22,345\u00a0data quality checks didn't pass",
        ],
        ['only skipped', { checks_skipped: 2 }, '2\u00a0data quality checks skipped'],
        ['one failure', { checks_passed: 6, checks_failed: 1 }, '1\u00a0data quality check failed'],
        ['one error', { checks_passed: 6, checks_errored: 1 }, "1\u00a0data quality check couldn't run"],
        [
            'failures and errors together',
            { checks_passed: 4, checks_failed: 2, checks_errored: 1 },
            "3\u00a0data quality checks didn't pass",
        ],
    ])('describes %s', (_, suiteRun, expected) => {
        expect(suiteRunToastMessage(buildSuiteRun(suiteRun))).toBe(expected)
    })
})
