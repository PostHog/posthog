import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ProjectType } from '~/types'

import { buildSignalReportListOrdering, inboxFiltersLogic } from './inboxFiltersLogic'

describe('inboxFiltersLogic', () => {
    describe('buildSignalReportListOrdering', () => {
        it('leads with the selected time field so "Newest first" surfaces the newest reports', () => {
            // The list is flat, so created_at must be the primary key — not a sub-sort within status buckets.
            expect(buildSignalReportListOrdering('created_at', 'desc')).toBe('-created_at,status,-updated_at')
        })

        it('leads with created_at ascending for "Oldest first"', () => {
            expect(buildSignalReportListOrdering('created_at', 'asc')).toBe('created_at,status,-updated_at')
        })

        it('leads with updated_at and drops the redundant tiebreak for "Last updated first"', () => {
            expect(buildSignalReportListOrdering('updated_at', 'desc')).toBe('-updated_at,status')
        })

        it('leads with priority for "Priority first"', () => {
            expect(buildSignalReportListOrdering('priority', 'asc')).toBe('priority,status,-updated_at')
        })
    })

    describe('reviewer preload mount guard', () => {
        let logic: ReturnType<typeof inboxFiltersLogic.build>

        beforeEach(() => {
            initKeaTests()
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/reports/available_reviewers': () => [200, {}],
                },
            })
            logic = inboxFiltersLogic()
        })

        afterEach(() => {
            logic.unmount()
        })

        it('preloads the reviewer roster on mount once the project id is known', async () => {
            await expectLogic(logic, () => {
                logic.mount()
            }).toDispatchActions(['loadAvailableReviewers', 'loadAvailableReviewersSuccess'])
        })

        it('skips the reviewer preload on mount while the project id is unknown', async () => {
            // Regression: `loadAvailableReviewers` → `api.signalReports.availableReviewers` routes
            // through `projectsDetail(getCurrentProjectId())`, which throws `Project ID is not known.`
            // when the id has not been seeded yet (early app init / OAuth bootstrap).
            ApiConfig.setCurrentProjectId(null as unknown as ProjectType['id'])

            await expectLogic(logic, () => {
                logic.mount()
            }).toNotHaveDispatchedActions(['loadAvailableReviewers'])
        })
    })
})
