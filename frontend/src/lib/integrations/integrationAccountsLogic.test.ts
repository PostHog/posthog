import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { integrationAccountsLogic } from './integrationAccountsLogic'

describe('integrationAccountsLogic', () => {
    let logic: ReturnType<typeof integrationAccountsLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('swallows the backend 400 and surfaces its message instead of propagating the rejection', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/external_data_sources/oauth_accounts/': () => [
                    400,
                    { type: 'validation_error', code: 'invalid', detail: 'Reconnect your account', attr: null },
                ],
            },
        })
        logic = integrationAccountsLogic({ id: 1, sourceType: 'GoogleSearchConsole' })
        logic.mount()

        // A handled 400 must resolve the loader (loadAccountsSuccess), never fail it — otherwise the
        // rejection reaches posthog-js's global handler and gets logged as an uncaught exception.
        await expectLogic(logic, () => {
            logic.actions.loadAccounts()
        })
            .toDispatchActions(['loadAccounts', 'setAccountsError', 'loadAccountsSuccess'])
            .toMatchValues({
                accounts: [],
                accountsError: 'Reconnect your account',
            })
    })

    it('still lets unexpected errors fail the loader so they stay visible in error tracking', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/external_data_sources/oauth_accounts/': () => [500, {}],
            },
        })
        logic = integrationAccountsLogic({ id: 1, sourceType: 'GoogleSearchConsole' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAccounts()
        }).toDispatchActions(['loadAccounts', 'loadAccountsFailure'])
    })
})
