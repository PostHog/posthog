import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { inboxErrorTrackingIssueLogic } from './inboxErrorTrackingIssueLogic'

describe('inboxErrorTrackingIssueLogic', () => {
    let logic: ReturnType<typeof inboxErrorTrackingIssueLogic.build>

    beforeEach(() => {
        initKeaTests()
        // The summary loader runs on mount too; keep it out of the way of the loadIssue assertions.
        jest.spyOn(api, 'query').mockResolvedValue({ results: [] } as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('settles loadIssue successfully on a 308 and keeps the merged target for the fallback link', async () => {
        jest.spyOn(api.errorTracking, 'getIssue').mockRejectedValue({
            status: 308,
            data: { issue_id: 'replacement-issue' },
        })

        logic = inboxErrorTrackingIssueLogic({
            issueId: 'merged-away-issue',
            fingerprint: 'fp-1',
            sourceType: 'issue_created',
        })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadIssue', 'setMergedToIssueId', 'loadIssueSuccess'])
            .toNotHaveDispatchedActions(['loadIssueFailure'])
            .toMatchValues({
                issue: null,
                // `mergedToIssueId` must survive the success listener so the card links to the survivor.
                mergedToIssueId: 'replacement-issue',
                mergedFailed: true,
            })
    })

    it('still fails loadIssue for a genuine non-308 error', async () => {
        jest.spyOn(api.errorTracking, 'getIssue').mockRejectedValue({ status: 500 })

        logic = inboxErrorTrackingIssueLogic({
            issueId: 'broken-issue',
            fingerprint: 'fp-2',
            sourceType: 'issue_created',
        })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadIssue', 'loadIssueFailure'])
            .toNotHaveDispatchedActions(['setMergedToIssueId'])
            .toMatchValues({
                issue: null,
                mergedToIssueId: null,
                mergedFailed: true,
            })
    })

    it('clears any merged target once a real issue loads', async () => {
        jest.spyOn(api.errorTracking, 'getIssue').mockResolvedValue({
            id: 'live-issue',
            first_seen: '2026-07-01T00:00:00Z',
        } as ErrorTrackingRelationalIssue)

        logic = inboxErrorTrackingIssueLogic({
            issueId: 'live-issue',
            fingerprint: 'fp-3',
            sourceType: 'issue_created',
        })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadIssue', 'loadIssueSuccess']).toMatchValues({
            mergedToIssueId: null,
            mergedFailed: false,
        })
    })
})
