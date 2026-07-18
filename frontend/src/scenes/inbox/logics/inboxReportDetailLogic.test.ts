/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SignalReport, SignalReportStatus } from '../types'
import { DIFF_UNAVAILABLE_MESSAGE, inboxReportDetailLogic, isExpectedDiffUnavailable } from './inboxReportDetailLogic'

const REPORT_ID = 'report-1'
const COMMIT_ARTEFACT_ID = 'commit-artefact-1'

const REPORT: SignalReport = {
    id: REPORT_ID,
    title: 'A report',
    summary: null,
    status: SignalReportStatus.READY,
    total_weight: 1,
    signal_count: 1,
    relevant_user_count: null,
    created_at: '2026-07-18T00:00:00Z',
    updated_at: '2026-07-18T00:00:00Z',
    artefact_count: 1,
    is_suggested_reviewer: false,
}

// One `commit` artefact so the artefact-load cascade fires `loadReportDiff` against its branch.
const mockReportEndpoints = (diffResponse: () => [number, Record<string, unknown>]): void => {
    useMocks({
        get: {
            '/api/projects/:team_id/signals/reports/:report_id/artefacts/': () => [
                200,
                {
                    count: 1,
                    results: [
                        {
                            id: COMMIT_ARTEFACT_ID,
                            type: 'commit',
                            content: { repository: 'PostHog/posthog', branch: 'gone', commit_sha: 'abc123' },
                            created_at: '2026-07-18T00:00:00Z',
                        },
                    ],
                },
            ],
            '/api/projects/:team_id/signals/reports/:report_id/signals/': () => [200, { signals: [] }],
            '/api/projects/:team_id/signals/reports/available_reviewers/': () => [200, {}],
            '/api/projects/:team_id/signals/reports/:report_id/artefacts/:artefact_id/diff/': diffResponse,
        },
    })
}

describe('inboxReportDetailLogic', () => {
    let logic: ReturnType<typeof inboxReportDetailLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    // A branch that was merged, deleted, or rewritten (backend answers 404), or a repo the GitHub
    // integration can't reach (also 404), must land on the "Files changed" failure card rather than
    // rejecting the loader — a reject flows through kea-loaders' onFailure into
    // `posthog.captureException`, which is exactly the handled-$exception noise this fixes.
    it.each([
        ['branch merged/deleted/rewritten or repo inaccessible (404)', 404],
        ['GitHub could not produce the diff (502)', 502],
    ])('surfaces the failure card without $exception noise when %s', async (_case, status) => {
        const captureException = jest.spyOn(posthog, 'captureException')
        mockReportEndpoints(() => [status, { error: 'GitHub could not produce the diff for this branch.' }])

        logic = inboxReportDetailLogic({ reportId: REPORT_ID, report: REPORT })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadReportDiff', 'loadReportDiffSuccess'])
            .toNotHaveDispatchedActions(['loadReportDiffFailure'])

        // Error card shown, not a skeleton (reportDiff null + reportDiffError set + not loading).
        expect(logic.values.reportDiff).toBeNull()
        expect(logic.values.reportDiffError).toBe(DIFF_UNAVAILABLE_MESSAGE)
        expect(logic.values.reportDiffLoading).toBe(false)
        // The whole point: no handled exception reported for this expected state.
        expect(captureException).not.toHaveBeenCalled()
    })

    // An unexpected server error must still reject so it stays observable in error tracking.
    it('still rejects (and reports) on an unexpected diff failure', async () => {
        mockReportEndpoints(() => [500, { error: 'boom' }])

        logic = inboxReportDetailLogic({ reportId: REPORT_ID, report: REPORT })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadReportDiff', 'loadReportDiffFailure'])
        expect(logic.values.reportDiff).toBeNull()
        expect(logic.values.reportDiffError).not.toBeNull()
    })

    it.each([
        [404, true],
        [502, true],
        [500, false],
        [400, false],
        [429, false],
        [undefined, false],
    ])('isExpectedDiffUnavailable classifies status %s as expected=%s', (status, expected) => {
        expect(isExpectedDiffUnavailable(status === undefined ? new Error('no status') : { status })).toBe(expected)
    })
})
