/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { credentialAccountsLogic } from './credentialAccountsLogic'

const accountFor = (value: string): Record<string, unknown> => ({
    value,
    display_name: value,
    is_primary: false,
    badges: [],
    group: null,
    secondary_text: null,
})

describe('credentialAccountsLogic', () => {
    let logic: ReturnType<typeof credentialAccountsLogic.build>

    afterEach(() => logic?.unmount())

    // The account picker fills in a lone account, and keeps a filled value. A listing that answers
    // for credentials the form has since replaced would leave the old account selected.
    it('drops a listing that answers for replaced credentials', async () => {
        let releaseFirst: () => void = () => {}
        const firstGate = new Promise<void>((resolve) => {
            releaseFirst = resolve
        })
        useMocks({
            post: {
                '/api/projects/:team_id/external_data_sources/credential_accounts/': async ({ request }) => {
                    const body = (await request.json()) as { credentials: { client_id: string } }
                    if (body.credentials.client_id === 'old') {
                        await firstGate
                    }
                    return [200, { accounts: [accountFor(`${body.credentials.client_id}-account`)] }]
                },
            },
        })
        initKeaTests()
        logic = credentialAccountsLogic({ sourceType: 'AppleSearchAds' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.setCredentials({ client_id: 'old' })).toDispatchActions([
            'loadCredentialAccounts',
        ])

        logic.actions.setCredentials({ client_id: 'new' })
        releaseFirst()
        await expectLogic(logic).toDispatchActions(['loadCredentialAccountsSuccess'])
        expect(logic.values.accounts).toEqual([])

        await expectLogic(logic).toDispatchActions(['loadCredentialAccounts', 'loadCredentialAccountsSuccess'])
        expect(logic.values.accounts.map((account) => account.value)).toEqual(['new-account'])
    })
})
