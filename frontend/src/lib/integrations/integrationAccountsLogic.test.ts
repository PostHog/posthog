/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { integrationAccountsLogic } from './integrationAccountsLogic'

describe('integrationAccountsLogic', () => {
    let logic: ReturnType<typeof integrationAccountsLogic.build>

    beforeEach(() => {
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => logic?.unmount())

    it('reports a rejected account listing so the connect scene stops being a telemetry blind spot', async () => {
        useMocks({
            get: {
                '/api/projects/:project_id/external_data_sources/oauth_accounts/': () => [
                    400,
                    { detail: 'Google Search Console rejected the credentials.' },
                ],
            },
        })
        initKeaTests()
        logic = integrationAccountsLogic({ id: 1, sourceType: 'GoogleSearchConsole' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadAccounts()).toFinishAllListeners()

        expect(logic.values.accountsError).toBe('Google Search Console rejected the credentials.')
        const invalidEvents = (posthog.capture as jest.Mock).mock.calls.filter(
            ([name]) => name === 'warehouse credentials invalid'
        )
        expect(invalidEvents).toHaveLength(1)
        expect(invalidEvents[0][1]).toMatchObject({
            sourceType: 'GoogleSearchConsole',
            errorMessage: 'Google Search Console rejected the credentials.',
            status: 400,
        })
    })

    it('does not report anything when the account listing succeeds', async () => {
        useMocks({
            get: {
                '/api/projects/:project_id/external_data_sources/oauth_accounts/': () => [
                    200,
                    { accounts: [{ value: 'https://example.com/', display_name: 'https://example.com/', badges: [] }] },
                ],
            },
        })
        initKeaTests()
        logic = integrationAccountsLogic({ id: 1, sourceType: 'GoogleSearchConsole' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadAccounts()).toFinishAllListeners()

        expect(logic.values.accountsError).toBeNull()
        const invalidEvents = (posthog.capture as jest.Mock).mock.calls.filter(
            ([name]) => name === 'warehouse credentials invalid'
        )
        expect(invalidEvents).toHaveLength(0)
    })
})
