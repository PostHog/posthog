import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import type { UserBasicType } from '~/types'

import { accountsList, accountsPartialUpdate } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_PAGE_SIZE, accountsLogic, savingRoleKey } from './accountsLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    accountsList: jest.fn(),
    accountsPartialUpdate: jest.fn(),
}))

const mockAccountsList = accountsList as jest.MockedFunction<typeof accountsList>
const mockAccountsPartialUpdate = accountsPartialUpdate as jest.MockedFunction<typeof accountsPartialUpdate>

const buildAccount = (overrides: Partial<AccountApi> = {}): AccountApi => ({
    id: 'acc-1',
    name: 'Acme',
    external_id: 'ext-1',
    properties: {
        csm: { id: 1, email: 'csm@example.com' },
        stripe_customer_id: 'cus_123',
    },
    tags: [],
    notebooks: [],
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
})

const buildUser = (overrides: Partial<UserBasicType> = {}): UserBasicType =>
    ({
        id: 42,
        uuid: 'user-uuid-42',
        first_name: 'Alex',
        last_name: 'Mercer',
        email: 'alex@example.com',
        ...overrides,
    }) as UserBasicType

describe('accountsLogic', () => {
    let logic: ReturnType<typeof accountsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockAccountsList.mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        })
        logic = accountsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('starts with empty filters', () => {
        expect(logic.values.searchQuery).toBe('')
        expect(logic.values.tagsFilter).toEqual([])
        expect(logic.values.allRolesUnassigned).toBe(false)
        expect(logic.values.csmFilter).toBeNull()
        expect(logic.values.accountExecutiveFilter).toBeNull()
        expect(logic.values.accountOwnerFilter).toBeNull()
        expect(logic.values.currentPage).toBe(1)
    })

    it('loads accounts on mount with default pagination', async () => {
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccountsList).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: ACCOUNTS_PAGE_SIZE,
            offset: 0,
        })
    })

    it('setTagsFilter updates the reducer and resets to page 1', async () => {
        logic.actions.setCurrentPage(3)
        logic.actions.setTagsFilter(['enterprise'])
        await expectLogic(logic).toMatchValues({
            tagsFilter: ['enterprise'],
            currentPage: 1,
        })
    })

    it('setSearchQuery updates the reducer and resets to page 1', async () => {
        logic.actions.setCurrentPage(3)
        logic.actions.setSearchQuery('acme')
        await expectLogic(logic).toMatchValues({
            searchQuery: 'acme',
            currentPage: 1,
        })
    })

    it('loadAccounts sends a trimmed search param', async () => {
        logic.actions.setSearchQuery('  acme  ')
        await expectLogic(logic).toFinishAllListeners()
        expect(mockAccountsList).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ search: 'acme' })
        )
    })

    it('loadAccounts omits the search param when the query is blank', async () => {
        logic.actions.setSearchQuery('   ')
        await expectLogic(logic).toFinishAllListeners()
        expect(mockAccountsList).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.not.objectContaining({ search: expect.anything() })
        )
    })

    it('setAllRolesUnassigned toggles the flag', () => {
        logic.actions.setAllRolesUnassigned(true)
        expect(logic.values.allRolesUnassigned).toBe(true)
    })

    it('setCsmFilter accepts a user id and null', () => {
        logic.actions.setCsmFilter(42)
        expect(logic.values.csmFilter).toBe(42)
        logic.actions.setCsmFilter(null)
        expect(logic.values.csmFilter).toBeNull()
    })

    it('loadAccounts sends tags as a JSON-encoded array string', async () => {
        logic.actions.setTagsFilter(['a', 'b'])
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccountsList).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ tags: '["a","b"]' })
        )
    })

    it('setting a role filter clears the all_roles_unassigned flag', async () => {
        logic.actions.setAllRolesUnassigned(true)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setCsmFilter(7)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allRolesUnassigned).toBe(false)
        expect(logic.values.csmFilter).toBe(7)
        expect(mockAccountsList).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ csm: '7', limit: ACCOUNTS_PAGE_SIZE, offset: 0 })
        )
        expect(mockAccountsList.mock.calls.at(-1)?.[1]).not.toHaveProperty('all_roles_unassigned')
    })

    it('enabling all_roles_unassigned clears any active role filters', async () => {
        logic.actions.setCsmFilter(7)
        logic.actions.setAccountExecutiveFilter(9)
        logic.actions.setAccountOwnerFilter(11)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setAllRolesUnassigned(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allRolesUnassigned).toBe(true)
        expect(logic.values.csmFilter).toBeNull()
        expect(logic.values.accountExecutiveFilter).toBeNull()
        expect(logic.values.accountOwnerFilter).toBeNull()

        const lastParams = mockAccountsList.mock.calls.at(-1)?.[1]
        expect(lastParams).toEqual(
            expect.objectContaining({ all_roles_unassigned: true, limit: ACCOUNTS_PAGE_SIZE, offset: 0 })
        )
        expect(lastParams).not.toHaveProperty('csm')
        expect(lastParams).not.toHaveProperty('account_executive')
        expect(lastParams).not.toHaveProperty('account_owner')
    })

    it('setCurrentPage updates the offset in the next request', async () => {
        logic.actions.setCurrentPage(3)
        await expectLogic(logic).toFinishAllListeners()
        expect(mockAccountsList).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ limit: ACCOUNTS_PAGE_SIZE, offset: 2 * ACCOUNTS_PAGE_SIZE })
        )
    })

    it('refresh triggers a fresh request with current filters', async () => {
        logic.actions.setTagsFilter(['priority'])
        await expectLogic(logic).toFinishAllListeners()
        mockAccountsList.mockClear()
        logic.actions.refresh()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockAccountsList).toHaveBeenCalledTimes(1)
        expect(mockAccountsList).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ tags: '["priority"]' })
        )
    })

    describe('updateAccountRole', () => {
        const existingAccount = buildAccount()

        beforeEach(async () => {
            mockAccountsList.mockResolvedValue({
                count: 1,
                next: null,
                previous: null,
                results: [existingAccount],
            })
            logic.actions.refresh()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('PATCHes the merged properties payload with the new assignment', async () => {
            const user = buildUser()
            const updated = buildAccount({
                properties: {
                    csm: { id: user.id, email: user.email },
                    stripe_customer_id: 'cus_123',
                },
            })
            mockAccountsPartialUpdate.mockResolvedValue(updated)

            logic.actions.updateAccountRole('acc-1', 'csm', user)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockAccountsPartialUpdate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'acc-1', {
                properties: {
                    csm: { id: user.id, email: user.email },
                    stripe_customer_id: 'cus_123',
                },
            })
            expect(logic.values.results[0].properties?.csm).toEqual({ id: user.id, email: user.email })
        })

        it('sends null when clearing an assignment', async () => {
            mockAccountsPartialUpdate.mockResolvedValue(
                buildAccount({ properties: { csm: null, stripe_customer_id: 'cus_123' } })
            )

            logic.actions.updateAccountRole('acc-1', 'csm', null)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockAccountsPartialUpdate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'acc-1', {
                properties: {
                    csm: null,
                    stripe_customer_id: 'cus_123',
                },
            })
        })

        it('flips savingRoles during the in-flight window', async () => {
            const key = savingRoleKey('acc-1', 'account_executive')
            let resolveUpdate!: (value: AccountApi) => void
            mockAccountsPartialUpdate.mockReturnValueOnce(
                new Promise<AccountApi>((resolve) => {
                    resolveUpdate = resolve
                })
            )

            logic.actions.updateAccountRole('acc-1', 'account_executive', buildUser())
            await new Promise<void>((r) => setTimeout(r, 0))
            expect(logic.values.savingRoles[key]).toBe(true)
            expect(logic.values.isRoleSaving('acc-1', 'account_executive')).toBe(true)

            resolveUpdate(buildAccount())
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.savingRoles[key]).toBeUndefined()
            expect(logic.values.isRoleSaving('acc-1', 'account_executive')).toBe(false)
        })

        it('leaves the row untouched on failure', async () => {
            mockAccountsPartialUpdate.mockRejectedValueOnce(new Error('boom'))

            logic.actions.updateAccountRole('acc-1', 'account_owner', buildUser())
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.results[0]).toEqual(existingAccount)
            expect(logic.values.isRoleSaving('acc-1', 'account_owner')).toBe(false)
        })

        it('is a no-op while a save for the same role is already in flight', async () => {
            let resolveFirst!: (value: AccountApi) => void
            mockAccountsPartialUpdate.mockReturnValueOnce(
                new Promise<AccountApi>((resolve) => {
                    resolveFirst = resolve
                })
            )

            logic.actions.updateAccountRole('acc-1', 'csm', buildUser({ id: 1, email: 'first@example.com' }))
            await new Promise<void>((r) => setTimeout(r, 0))
            logic.actions.updateAccountRole('acc-1', 'csm', buildUser({ id: 2, email: 'second@example.com' }))
            await new Promise<void>((r) => setTimeout(r, 0))

            expect(mockAccountsPartialUpdate).toHaveBeenCalledTimes(1)

            resolveFirst(buildAccount())
            await expectLogic(logic).toFinishAllListeners()
        })
    })
})
