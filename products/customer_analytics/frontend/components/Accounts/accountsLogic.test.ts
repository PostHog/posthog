import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { accountsList } from 'products/customer_analytics/frontend/generated/api'

import { ACCOUNTS_PAGE_SIZE, accountsLogic } from './accountsLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    accountsList: jest.fn(),
}))

const mockAccountsList = accountsList as jest.MockedFunction<typeof accountsList>

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
})
