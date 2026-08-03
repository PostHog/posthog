/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { INBOX_SCOPE_ENTIRE_PROJECT, INBOX_SCOPE_FOR_YOU, InboxFlatListTabKey, InboxScope } from '../types'
import { inboxBulkActionsLogic } from './inboxBulkActionsLogic'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic, shouldDefaultToEntireProject } from './reportListLogic'

describe('reportListLogic', () => {
    describe('shouldDefaultToEntireProject', () => {
        const base = {
            tabKey: 'pulls' as InboxFlatListTabKey,
            scope: INBOX_SCOPE_FOR_YOU as InboxScope,
            hasUserChosenScope: false,
            hasResolvedUser: true,
            count: 0 as number | null,
        }

        it('switches to Entire project when a fresh user has zero assigned PRs', () => {
            expect(shouldDefaultToEntireProject(base)).toBe(true)
        })

        it.each<[string, Partial<typeof base>]>([
            // The user has PRs assigned – keep them on For you.
            ['user has assigned PRs', { count: 3 }],
            // The user deliberately picked a scope – never override it, even with zero PRs.
            ['user chose their scope', { hasUserChosenScope: true }],
            // Only the Pull requests tab (their assigned PRs) drives the default.
            ['not the pulls tab', { tabKey: 'reports' as InboxFlatListTabKey }],
            // Already off For you – nothing to default.
            ['already entire project', { scope: INBOX_SCOPE_ENTIRE_PROJECT as InboxScope }],
            // Count for For-you scope is only meaningful once the user's uuid has resolved.
            ['user not resolved yet', { hasResolvedUser: false }],
            // Count request in flight / failed (null) is not treated as "zero".
            ['count not loaded', { count: null }],
        ])('stays put when %s', (_label, override) => {
            expect(shouldDefaultToEntireProject({ ...base, ...override })).toBe(false)
        })
    })

    describe('reconciling an archive broadcast from another surface', () => {
        let serverReportIds: string[]

        const mountReportsTab = async (): Promise<ReturnType<typeof reportListLogic.build>> => {
            serverReportIds = ['report-1', 'report-2']
            useMocks({
                get: {
                    // Mounting the list connects `inboxFiltersLogic`, which loads the reviewer picker.
                    '/api/projects/:team_id/signals/reports/available_reviewers/': () => [200, {}],
                    '/api/projects/:team_id/signals/reports/': () => [
                        200,
                        {
                            count: serverReportIds.length,
                            next: null,
                            previous: null,
                            results: serverReportIds.map((id) => ({ id, title: id, status: 'ready' })),
                        },
                    ],
                },
            })
            inboxBulkActionsLogic.mount()
            const logic = reportListLogic({ tabKey: 'reports', listParams: INBOX_FLAT_TAB_LIST_PARAMS.reports })
            logic.mount()
            logic.actions.loadReports()
            await expectLogic(logic).toFinishAllListeners()
            return logic
        }

        beforeEach(() => {
            initKeaTests()
        })

        it('drops the row before the refetch lands, so the archive never looks like it failed', async () => {
            const logic = await mountReportsTab()
            expect(logic.values.reports.map((report) => report.id)).toEqual(['report-1', 'report-2'])

            serverReportIds = ['report-2']
            inboxBulkActionsLogic.actions.reportArchived('report-1')

            // Synchronously, i.e. while the reconciling refetch is still in flight – otherwise the
            // archived report sits at the top of the list the user is returned to (the archive bumps
            // its `updated_at`, and the list sorts on that).
            expect(logic.values.reports.map((report) => report.id)).toEqual(['report-2'])
            expect(logic.values.totalCount).toBe(1)

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.reports.map((report) => report.id)).toEqual(['report-2'])
        })

        it('leaves counts alone when the archived report was never in this list', async () => {
            const logic = await mountReportsTab()

            inboxBulkActionsLogic.actions.reportArchived('report-from-another-tab')

            expect(logic.values.reports.map((report) => report.id)).toEqual(['report-1', 'report-2'])
            expect(logic.values.totalCount).toBe(2)
            expect(logic.values.count).toBe(2)
        })
    })
})
