import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { INBOX_SCOPE_ENTIRE_PROJECT, INBOX_SCOPE_FOR_YOU, InboxFlatListTabKey, InboxScope } from '../types'
import { reportListLogic, shouldDefaultToEntireProject } from './reportListLogic'

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

    describe('list loaders swallow network-level failures', () => {
        let logic: ReturnType<typeof reportListLogic.build>

        beforeEach(() => {
            initKeaTests()
            // The shared reviewer roster loads on mount via the connected filters logic; stub it so
            // mounting doesn't hit the network and can't interfere with the list loader assertions.
            jest.spyOn(api.signalReports, 'availableReviewers').mockResolvedValue([])
        })

        afterEach(() => {
            logic?.unmount()
            jest.restoreAllMocks()
        })

        function mountLogic(): void {
            logic = reportListLogic({ tabKey: 'reports', listParams: {} })
            logic.mount()
        }

        // handleFetch wraps a native fetch failure (dropped connectivity, navigation away, ad-blocker)
        // as an ApiError with no status, because the request never reached a response.
        const networkError = (): ApiError => new ApiError('Failed to fetch', undefined)

        it.each<[string, string, string]>([
            ['loadReports', 'loadReportsSuccess', 'loadReportsFailure'],
            ['loadMoreReports', 'loadMoreReportsSuccess', 'loadMoreReportsFailure'],
            ['loadCount', 'loadCountSuccess', 'loadCountFailure'],
        ])('%s resolves quietly instead of surfacing a captured exception', async (action, success, failure) => {
            jest.spyOn(api.signalReports, 'list').mockRejectedValue(networkError())
            mountLogic()

            await expectLogic(logic, () => {
                ;(logic.actions as any)[action]()
            })
                .toDispatchActions([action, success])
                .toNotHaveDispatchedActions([failure])

            // Nothing was loaded, so the tab falls back to its empty/retry state rather than an error.
            expect(logic.values.isLoaded).toBe(false)
        })

        it('a genuine server error still propagates as a failure', async () => {
            jest.spyOn(api.signalReports, 'list').mockRejectedValue(new ApiError('Server error', 500))
            mountLogic()

            await expectLogic(logic, () => {
                logic.actions.loadReports()
            }).toDispatchActions(['loadReports', 'loadReportsFailure'])
        })
    })
})
