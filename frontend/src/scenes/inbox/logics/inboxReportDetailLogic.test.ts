import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SignalReport } from '../types'
import { inboxReportDetailLogic } from './inboxReportDetailLogic'

const REPORT = { id: 'report-1', status: 'ready', title: 'Checkout errors spiked' } as unknown as SignalReport

describe('inboxReportDetailLogic', () => {
    let logic: ReturnType<typeof inboxReportDetailLogic.build>

    describe('feedback note submission', () => {
        let feedbackPosts: number

        beforeEach(() => {
            feedbackPosts = 0
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [] },
                    '/api/projects/:team_id/signals/reports/:id/signals/': [],
                    '/api/projects/:team_id/signals/reports/available_reviewers/': [],
                },
                post: {
                    '/api/projects/:team_id/signals/reports/:id/feedback/': () => {
                        feedbackPosts += 1
                        return [200, { forwarded: true }]
                    },
                },
            })
            initKeaTests()
            logic = inboxReportDetailLogic({ reportId: REPORT.id, report: REPORT })
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        it('posts once on a double-click and lets a revised note through after re-rating', async () => {
            logic.actions.rateReport('positive')
            // A double-click dispatches submit twice before the first request settles.
            logic.actions.submitFeedbackNote('the repro steps were right')
            logic.actions.submitFeedbackNote('the repro steps were right')
            await expectLogic(logic).toFinishAllListeners()

            expect(feedbackPosts).toBe(1)
            expect(logic.values.feedbackNoteSubmitting).toBe(false)

            // Re-rating reopens the note flow; the guard must have reset or this submit is silently dropped.
            logic.actions.rateReport('negative')
            logic.actions.submitFeedbackNote('actually this was stale')
            await expectLogic(logic).toFinishAllListeners()

            expect(feedbackPosts).toBe(2)
        })
    })

    describe('branch diff failures', () => {
        let diffStatus: number
        let toastError: jest.SpyInstance

        beforeEach(() => {
            diffStatus = 404
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [] },
                    '/api/projects/:team_id/signals/reports/:id/signals/': [],
                    '/api/projects/:team_id/signals/reports/available_reviewers/': [],
                    '/api/projects/:team_id/signals/reports/:id/artefacts/:artefact_id/diff/': () => [
                        diffStatus,
                        { error: "Branch 'fix/checkout' or repository 'acme/app' was not found on GitHub." },
                    ],
                },
            })
            initKeaTests()
            toastError = jest.spyOn(lemonToast, 'error').mockReturnValue(undefined as any)
            logic = inboxReportDetailLogic({ reportId: REPORT.id, report: REPORT })
            logic.mount()
        })

        afterEach(() => {
            toastError.mockRestore()
            logic.unmount()
        })

        // Opening a report whose branch was merged and deleted used to fire a red toast on top of the
        // inline message, because the diff loader wasn't in initKea's `ERROR_FILTER_ALLOW_LIST`.
        it.each([
            [404, { message: 'This branch is no longer on GitHub. It was probably merged and deleted.', gone: true }],
            [502, { message: "Couldn't load the diff from GitHub. Try again in a moment.", gone: false }],
        ])('keeps a %s inline and off the toast stack', async (status, expected) => {
            diffStatus = status
            logic.actions.loadReportDiff({ artefactId: 'artefact-1' })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.reportDiffError).toEqual(expected)
            expect(toastError).not.toHaveBeenCalled()
        })
    })
})
