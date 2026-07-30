/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SignalReport, SignalReportStatus } from '../types'
import { inboxReportDetailLogic } from './inboxReportDetailLogic'

const REPORT_ID = '019fb0b3-08b6-7b4f-adec-5335bec75ce2'

const PR_CHECKS_POLL_INTERVAL_MS = 15000

const report = {
    id: REPORT_ID,
    // A dismissed report whose detail still advertises an implementation PR — the state that used to
    // 404 the PR endpoints forever.
    status: SignalReportStatus.SUPPRESSED,
    title: 'Test report',
    summary: 'Test summary',
    implementation_pr_url: 'https://github.com/PostHog/posthog/pull/7',
} as unknown as SignalReport

describe('inboxReportDetailLogic', () => {
    let logic: ReturnType<typeof inboxReportDetailLogic.build>
    let prChecksRequests: number

    const mountWithPrChecks = async (checksResponse: () => [number, Record<string, any>]): Promise<void> => {
        prChecksRequests = 0
        useMocks({
            get: {
                [`/api/projects/:team_id/signals/reports/${REPORT_ID}/artefacts/`]: () => [
                    200,
                    { count: 0, results: [] },
                ],
                [`/api/projects/:team_id/signals/reports/${REPORT_ID}/signals/`]: () => [200, { signals: [] }],
                '/api/projects/:team_id/signals/reports/available_reviewers/': () => [200, {}],
                [`/api/projects/:team_id/signals/reports/${REPORT_ID}/pr_checks/`]: () => {
                    prChecksRequests += 1
                    return checksResponse()
                },
                [`/api/projects/:team_id/signals/reports/${REPORT_ID}/pr_comments/`]: () => [200, { comments: [] }],
            },
        })
        logic = inboxReportDetailLogic({ reportId: REPORT_ID, report })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
    }

    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    // Regression: a 404 is permanent for this report, but the poll kept retrying it every 15s for as
    // long as the tab stayed open, toasting the reader and filing an error-tracking event each tick.
    it('stops polling PR checks once the request 404s', async () => {
        await mountWithPrChecks(() => [404, { detail: 'Not found.' }])
        expect(prChecksRequests).toBe(1)
        expect(logic.values.prChecksUnresolvable).toBe(true)
        expect(logic.values.prChecksError).toMatch(/pull request/)

        await jest.advanceTimersByTimeAsync(PR_CHECKS_POLL_INTERVAL_MS * 4)

        expect(prChecksRequests).toBe(1)
    })

    it('keeps polling PR checks while the request succeeds', async () => {
        await mountWithPrChecks(() => [200, { checks: [] }])
        expect(prChecksRequests).toBe(1)

        await jest.advanceTimersByTimeAsync(PR_CHECKS_POLL_INTERVAL_MS)

        expect(prChecksRequests).toBe(2)
        expect(logic.values.prChecksUnresolvable).toBe(false)
    })
})
