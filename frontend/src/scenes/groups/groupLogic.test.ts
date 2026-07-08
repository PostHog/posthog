import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { groupLogic, resolveBackNavigation } from './groupLogic'

describe('groupLogic', () => {
    describe('resolveBackNavigation', () => {
        it('returns the sanitized internal path and name', () => {
            expect(resolveBackNavigation({ backUrl: '/customer_analytics/accounts', backName: 'Accounts' })).toEqual({
                url: '/customer_analytics/accounts',
                name: 'Accounts',
            })
        })

        it('preserves search and hash on the internal path', () => {
            expect(
                resolveBackNavigation({
                    backUrl: '/customer_analytics/accounts?tab=usage#view=abc',
                    backName: 'Accounts',
                })
            ).toEqual({ url: '/customer_analytics/accounts?tab=usage#view=abc', name: 'Accounts' })
        })

        it('rejects an absolute external URL (open redirect guard)', () => {
            expect(resolveBackNavigation({ backUrl: 'https://evil.com', backName: 'Accounts' })).toBeNull()
        })

        it('rejects a protocol-relative URL', () => {
            expect(resolveBackNavigation({ backUrl: '//evil.com' })).toBeNull()
        })

        it('returns null when backUrl is absent', () => {
            expect(resolveBackNavigation({})).toBeNull()
        })

        it('falls back to a default name when backName is missing', () => {
            expect(resolveBackNavigation({ backUrl: '/groups/0/acme' })).toEqual({
                url: '/groups/0/acme',
                name: 'Back',
            })
        })
    })

    describe('loadGroup', () => {
        let logic: ReturnType<typeof groupLogic.build>

        beforeEach(() => {
            initKeaTests()
            window.POSTHOG_APP_CONTEXT = { current_team: { id: 123, group_types: [] } } as unknown as AppContext
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('renders the not-found state instead of throwing when the group is missing', async () => {
            // A missing group key resolves to a 404 - the loader should treat it as not-found
            // (groupData stays null via success) rather than surfacing a noisy exception.
            useMocks({
                get: {
                    '/api/environments/:team_id/groups/find': () => [404, {}],
                },
            })

            logic = groupLogic({ groupTypeIndex: 0, groupKey: 'does-not-exist' })
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadGroup', 'loadGroupSuccess'])
                .toNotHaveDispatchedActions(['loadGroupFailure'])
                .toMatchValues({ groupData: null })
        })

        it('surfaces genuinely unexpected failures', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/groups/find': () => [500, {}],
                },
            })

            logic = groupLogic({ groupTypeIndex: 0, groupKey: 'boom' })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadGroup', 'loadGroupFailure'])
        })
    })
})
