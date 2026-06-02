import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import type { AccountsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { UserBasicType } from '~/types'

import { accountsPartialUpdate, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    ACCOUNTS_HOGQL_DEFAULT_SELECT,
    ACCOUNTS_NAME_COLUMN,
    accountsColumnConfigLogic,
} from './accountsColumnConfigLogic'
import { accountsLogic, savingRoleKey } from './accountsLogic'

// `hogqlQuery.source` is typed as the full DataTableNode source union; this logic
// always produces an AccountsQuery, so narrow once for the orderBy assertions.
const orderByOf = (source: unknown): AccountsQuery['orderBy'] => (source as AccountsQuery).orderBy

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    accountsRetrieve: jest.fn(),
    accountsPartialUpdate: jest.fn(),
}))

const mockAccountsRetrieve = accountsRetrieve as jest.MockedFunction<typeof accountsRetrieve>
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
    })

    it('setTagsFilter updates the reducer', () => {
        logic.actions.setTagsFilter(['enterprise'])
        expect(logic.values.tagsFilter).toEqual(['enterprise'])
    })

    it('setSearchQuery updates the reducer', () => {
        logic.actions.setSearchQuery('acme')
        expect(logic.values.searchQuery).toBe('acme')
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

    it('setting a role filter clears the all_roles_unassigned flag', async () => {
        logic.actions.setAllRolesUnassigned(true)
        logic.actions.setCsmFilter(7)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allRolesUnassigned).toBe(false)
        expect(logic.values.csmFilter).toBe(7)
    })

    it('enabling all_roles_unassigned clears any active role filters', async () => {
        logic.actions.setCsmFilter(7)
        logic.actions.setAccountExecutiveFilter(9)
        logic.actions.setAccountOwnerFilter(11)
        logic.actions.setAllRolesUnassigned(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allRolesUnassigned).toBe(true)
        expect(logic.values.csmFilter).toBeNull()
        expect(logic.values.accountExecutiveFilter).toBeNull()
        expect(logic.values.accountOwnerFilter).toBeNull()
    })

    describe('sortOrder', () => {
        it('starts unset and produces no orderBy on the AccountsQuery', () => {
            expect(logic.values.sortOrder).toBeNull()
            expect(orderByOf(logic.values.hogqlQuery.source)).toBeUndefined()
        })

        it('toggleSort on a fresh column starts ascending', () => {
            logic.actions.toggleSort('notebook_count')
            expect(logic.values.sortOrder).toEqual({ column: 'notebook_count', direction: 'asc' })
            expect(orderByOf(logic.values.hogqlQuery.source)).toEqual(['notebook_count'])
        })

        it('toggleSort cycles asc -> desc -> null on repeated clicks', () => {
            logic.actions.toggleSort('notebook_count')
            expect(logic.values.sortOrder?.direction).toBe('asc')
            logic.actions.toggleSort('notebook_count')
            expect(logic.values.sortOrder).toEqual({ column: 'notebook_count', direction: 'desc' })
            expect(orderByOf(logic.values.hogqlQuery.source)).toEqual(['notebook_count DESC'])
            logic.actions.toggleSort('notebook_count')
            expect(logic.values.sortOrder).toBeNull()
            expect(orderByOf(logic.values.hogqlQuery.source)).toBeUndefined()
        })

        it('toggleSort on a different column resets to ascending', () => {
            logic.actions.toggleSort('notebook_count')
            logic.actions.toggleSort('notebook_count') // desc
            logic.actions.toggleSort('csm')
            expect(logic.values.sortOrder).toEqual({ column: 'csm', direction: 'asc' })
            expect(orderByOf(logic.values.hogqlQuery.source)).toEqual(['tupleElement(csm, 2)'])
        })

        it('csm desc produces tupleElement(csm, 2) DESC', () => {
            logic.actions.toggleSort('csm')
            logic.actions.toggleSort('csm')
            expect(orderByOf(logic.values.hogqlQuery.source)).toEqual(['tupleElement(csm, 2) DESC'])
        })

        it('account_executive sort uses the tupleElement expression', () => {
            logic.actions.toggleSort('account_executive')
            expect(orderByOf(logic.values.hogqlQuery.source)).toEqual(['tupleElement(account_executive, 2)'])
        })

        it('account_owner sort uses the tupleElement expression', () => {
            logic.actions.toggleSort('account_owner')
            expect(orderByOf(logic.values.hogqlQuery.source)).toEqual(['tupleElement(account_owner, 2)'])
        })

        it('arbitrary column sorts by its alias directly', () => {
            logic.actions.toggleSort('name')
            expect(orderByOf(logic.values.hogqlQuery.source)).toEqual(['name'])
            logic.actions.toggleSort('name')
            expect(orderByOf(logic.values.hogqlQuery.source)).toEqual(['name DESC'])
        })
    })

    describe('selectColumns', () => {
        it('starts with the default select and includes the mandatory name column', () => {
            const config = accountsColumnConfigLogic.findMounted()
            expect(config?.values.selectColumns).toEqual(ACCOUNTS_HOGQL_DEFAULT_SELECT)
            expect(config?.values.selectColumns).toContain(ACCOUNTS_NAME_COLUMN)
        })

        it('hogqlQuery.source.select equals selectColumns verbatim — no pinned aliases', () => {
            const config = accountsColumnConfigLogic.findMounted()
            const source = logic.values.hogqlQuery.source as AccountsQuery
            expect(source.select).toEqual(config?.values.selectColumns)
        })

        it('refuses to remove the name column via unselectColumn', () => {
            const config = accountsColumnConfigLogic.findMounted()
            config?.actions.unselectColumn(ACCOUNTS_NAME_COLUMN)
            expect(config?.values.selectColumns).toContain(ACCOUNTS_NAME_COLUMN)
        })

        it('re-inserts the name column when setSelectColumns omits it', () => {
            const config = accountsColumnConfigLogic.findMounted()
            config?.actions.setSelectColumns(['csm', 'account_executive'])
            expect(config?.values.selectColumns).toEqual([ACCOUNTS_NAME_COLUMN, 'csm', 'account_executive'])
        })

        it('keeps user ordering when setSelectColumns already contains name', () => {
            const config = accountsColumnConfigLogic.findMounted()
            config?.actions.setSelectColumns(['csm', ACCOUNTS_NAME_COLUMN, 'account_executive'])
            expect(config?.values.selectColumns).toEqual(['csm', ACCOUNTS_NAME_COLUMN, 'account_executive'])
        })
    })

    describe('updateAccountRole', () => {
        const existingAccount = buildAccount()

        beforeEach(() => {
            mockAccountsRetrieve.mockResolvedValue(existingAccount)
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

            expect(mockAccountsRetrieve).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'acc-1')
            expect(mockAccountsPartialUpdate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'acc-1', {
                properties: {
                    csm: { id: user.id, email: user.email },
                    stripe_customer_id: 'cus_123',
                },
            })
            expect(logic.values.accountOverrides['acc-1']).toEqual(updated)
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

        it('leaves overrides untouched on failure', async () => {
            mockAccountsPartialUpdate.mockRejectedValueOnce(new Error('boom'))

            logic.actions.updateAccountRole('acc-1', 'account_owner', buildUser())
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.accountOverrides['acc-1']).toBeUndefined()
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
