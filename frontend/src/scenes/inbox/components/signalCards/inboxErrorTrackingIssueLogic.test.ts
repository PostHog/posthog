import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { inboxErrorTrackingIssueLogic } from './inboxErrorTrackingIssueLogic'

const RELATIONAL_ISSUE: ErrorTrackingRelationalIssue = {
    id: 'issue-1',
    name: 'TypeError: boom',
    description: null,
    assignee: null,
    status: 'active',
    first_seen: '2026-07-08T12:00:00Z',
}

describe('inboxErrorTrackingIssueLogic', () => {
    let logic: ReturnType<typeof inboxErrorTrackingIssueLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.errorTracking, 'getIssue').mockResolvedValue(RELATIONAL_ISSUE)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    function mountLogic(): void {
        logic = inboxErrorTrackingIssueLogic({
            issueId: 'issue-1',
            fingerprint: 'fp-1',
            sourceType: 'issue_created',
        })
        logic.mount()
    }

    it('degrades to the issue row without aggregations when the summary query is throttled', async () => {
        // The concurrency limiter surfaces a 429 with this exact user message under ClickHouse pressure.
        jest.spyOn(api, 'query').mockRejectedValue(
            new ApiError('Too many queries are running right now — please try again in a moment.', 429)
        )

        mountLogic()

        // The summary loader resolves into the degraded state rather than failing (no thrown exception).
        await expectLogic(logic)
            .toDispatchActions(['loadSummary', 'setSummaryUnavailable', 'loadSummarySuccess'])
            .toNotHaveDispatchedActions(['loadSummaryFailure'])
            .toMatchValues({
                summary: null,
                summaryUnavailable: true,
                mergedFailed: false,
            })

        // The relational row still renders; aggregations are simply absent.
        expect(logic.values.mergedIssue).toMatchObject({ id: 'issue-1', aggregations: undefined })
    })

    it('rethrows unexpected summary failures instead of silently degrading', async () => {
        jest.spyOn(api, 'query').mockRejectedValue(new ApiError('Bad request', 400))

        mountLogic()

        await expectLogic(logic)
            .toDispatchActions(['loadSummaryFailure'])
            .toNotHaveDispatchedActions(['setSummaryUnavailable'])
            .toMatchValues({ summaryUnavailable: false })
    })

    it('falls back to a link when the issue was merged away (308)', async () => {
        const mergedError = new ApiError('Moved', 308, undefined, { issue_id: 'issue-2' })
        jest.spyOn(api.errorTracking, 'getIssue').mockRejectedValue(mergedError)
        jest.spyOn(api, 'query').mockResolvedValue({ results: [] } as any)

        mountLogic()

        await expectLogic(logic).toDispatchActions(['loadIssueFailure']).toMatchValues({
            mergedToIssueId: 'issue-2',
            mergedFailed: true,
            mergedIssue: null,
        })
    })
})
