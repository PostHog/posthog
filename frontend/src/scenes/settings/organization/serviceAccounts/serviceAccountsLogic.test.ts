import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { serviceAccountsLogic } from './serviceAccountsLogic'

const account = {
    id: '11111111-1111-4111-8111-111111111111',
    name: 'Build runner',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
}

describe('serviceAccountsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        router.actions.push('/settings/organization-members#service-accounts')
    })

    it('includes accounts on later pages in search results', async () => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/service_accounts/': ({ request }) =>
                    new URL(request.url).searchParams.get('offset') === '0'
                        ? { results: [account], next: 'http://localhost/next' }
                        : { results: [{ ...account, id: 'second', name: 'Export runner' }], next: null },
            },
        })
        const logic = serviceAccountsLogic({ organizationId: 'org-one' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadAccountsSuccess'])
        logic.actions.setSearch(' export ')
        expect(logic.values.filteredAccounts.map((item) => item.id)).toEqual(['second'])
    })

    it('keeps a failed form open and opens the created account after retry', async () => {
        let fail = true
        const bodies: unknown[] = []
        useMocks({
            get: { '/api/organizations/:organization_id/service_accounts/': { results: [], next: null } },
            post: {
                '/api/organizations/:organization_id/service_accounts/': async ({ request }) => {
                    bodies.push(await request.json())
                    return fail ? [500, { detail: 'Unavailable' }] : [201, account]
                },
            },
        })
        const logic = serviceAccountsLogic({ organizationId: 'org-one' })
        logic.mount()
        logic.actions.setCreating(true)
        logic.actions.setNewAccountValue('name', ' Build runner ')
        await expectLogic(logic, () => logic.actions.submitNewAccount()).toDispatchActions(['submitNewAccountFailure'])
        expect(logic.values.creating).toBe(true)
        expect(logic.values.createFailed).toBe(true)
        expect(logic.values.newAccount.name).toBe(' Build runner ')
        fail = false
        await expectLogic(logic, () => logic.actions.submitNewAccount()).toDispatchActions(['submitNewAccountSuccess'])
        expect(bodies).toEqual([{ name: 'Build runner' }, { name: 'Build runner' }])
        expect(logic.values.creating).toBe(false)
        expect(logic.values.selectedAccountId).toBe(account.id)
        expect(router.values.searchParams.service_account).toBe(account.id)
        logic.actions.selectAccount(null)
        expect(router.values.searchParams.service_account).toBeUndefined()
    })

    it('restores selection from a detail link and browser navigation', () => {
        useMocks({ get: { '/api/organizations/:organization_id/service_accounts/': { results: [], next: null } } })
        router.actions.push(`/settings/organization-members?service_account=${account.id}#service-accounts`)
        const logic = serviceAccountsLogic({ organizationId: 'org-one' })
        logic.mount()
        expect(logic.values.selectedAccountId).toBe(account.id)
        router.actions.push('/settings/organization-members#service-accounts')
        expect(logic.values.selectedAccountId).toBeNull()
    })
})
