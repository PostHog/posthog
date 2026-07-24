import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

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

    describe('loadCount', () => {
        let logic: ReturnType<typeof reportListLogic.build>

        beforeEach(() => {
            initKeaTests()
            // Mounting the connected filters logic loads the reviewer roster; stub it so it can't
            // interfere with the count loader assertions.
            jest.spyOn(api.signalReports, 'availableReviewers').mockResolvedValue([])
        })

        afterEach(() => {
            logic?.unmount()
            jest.restoreAllMocks()
        })

        // api.get pipes the body through getJSONOrNull, which resolves to null for any 2xx response
        // that isn't valid JSON (empty body, 204, an HTML login/redirect page on session expiry).
        // The count then has to fall back to zero rather than dereferencing null into a captured
        // "Cannot read properties of null (reading 'count')" TypeError.
        it('resolves to 0 when the API returns an empty (null) body', async () => {
            jest.spyOn(api.signalReports, 'list').mockResolvedValue(null as any)

            logic = reportListLogic({ tabKey: 'reports', listParams: {} })
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadCount', 'loadCountSuccess'])
                .toNotHaveDispatchedActions(['loadCountFailure'])
                .toMatchValues({ count: 0 })
        })
    })
})
