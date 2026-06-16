import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { AccountsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { UserBasicType, UserType } from '~/types'

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
        expect(logic.values.csmFilter).toEqual([])
        expect(logic.values.accountExecutiveFilter).toEqual([])
        expect(logic.values.accountOwnerFilter).toEqual([])
    })

    it('setTagsFilter updates the reducer', () => {
        logic.actions.setTagsFilter(['enterprise'])
        expect(logic.values.tagsFilter).toEqual(['enterprise'])
    })

    it('setSearchQuery updates the reducer', () => {
        logic.actions.setSearchQuery('acme')
        expect(logic.values.searchQuery).toBe('acme')
    })

    it('setSearchInput updates the input immediately but defers the committed searchQuery', () => {
        logic.actions.setSearchInput('acme')
        expect(logic.values.searchInput).toBe('acme')
        // Debounced: the query-driving value is not committed synchronously.
        expect(logic.values.searchQuery).toBe('')
    })

    it('carries the overview tile metrics on the same AccountsQuery', () => {
        const source = logic.values.hogqlQuery.source as AccountsQuery
        expect(source.metrics).toEqual(['count()'])
    })

    it('setAllRolesUnassigned toggles the flag', () => {
        logic.actions.setAllRolesUnassigned(true)
        expect(logic.values.allRolesUnassigned).toBe(true)
    })

    it('setCsmFilter accepts a list of user ids and clears with an empty list', () => {
        logic.actions.setCsmFilter([42])
        expect(logic.values.csmFilter).toEqual([42])
        logic.actions.setCsmFilter([42, 43])
        expect(logic.values.csmFilter).toEqual([42, 43])
        logic.actions.setCsmFilter([])
        expect(logic.values.csmFilter).toEqual([])
    })

    it('setting a role filter clears the all_roles_unassigned flag', async () => {
        logic.actions.setAllRolesUnassigned(true)
        logic.actions.setCsmFilter([7])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allRolesUnassigned).toBe(false)
        expect(logic.values.csmFilter).toEqual([7])
    })

    it('enabling all_roles_unassigned clears any active role filters', async () => {
        logic.actions.setCsmFilter([7])
        logic.actions.setAccountExecutiveFilter([9])
        logic.actions.setAccountOwnerFilter([11])
        logic.actions.setAllRolesUnassigned(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allRolesUnassigned).toBe(true)
        expect(logic.values.csmFilter).toEqual([])
        expect(logic.values.accountExecutiveFilter).toEqual([])
        expect(logic.values.accountOwnerFilter).toEqual([])
    })

    describe('assignedTo filter and "my accounts" shortcut', () => {
        const CURRENT_USER_ID = 42

        beforeEach(() => {
            userLogic.actions.loadUserSuccess(buildUser({ id: CURRENT_USER_ID }) as unknown as UserType)
        })

        it('starts disabled and adds nothing to the query', () => {
            expect(logic.values.assignedToCurrentUser).toBe(false)
            expect(logic.values.assignedToFilter).toEqual([])
            expect((logic.values.hogqlQuery.source as AccountsQuery).assignedToUserIds).toBeUndefined()
        })

        it('the "My accounts" checkbox resolves to the current user id', () => {
            logic.actions.setAssignedToCurrentUser(true)
            expect(logic.values.assignedToFilter).toEqual([CURRENT_USER_ID])
            expect(logic.values.assignedToCurrentUser).toBe(true)
            expect((logic.values.hogqlQuery.source as AccountsQuery).assignedToUserIds).toEqual([CURRENT_USER_ID])
        })

        it('"My accounts" is checked only when the filter is exactly the current user', () => {
            logic.actions.setAssignedToFilter([CURRENT_USER_ID])
            expect(logic.values.assignedToCurrentUser).toBe(true)
            logic.actions.setAssignedToFilter([99])
            expect(logic.values.assignedToCurrentUser).toBe(false)
            logic.actions.setAssignedToFilter([CURRENT_USER_ID, 99])
            expect(logic.values.assignedToCurrentUser).toBe(false)
        })

        it('toggling the checkbox off clears the filter', () => {
            logic.actions.setAssignedToCurrentUser(true)
            logic.actions.setAssignedToCurrentUser(false)
            expect(logic.values.assignedToFilter).toEqual([])
            expect((logic.values.hogqlQuery.source as AccountsQuery).assignedToUserIds).toBeUndefined()
        })

        it('the Assigned to picker accepts explicit ids', () => {
            logic.actions.setAssignedToFilter([7, 9])
            expect(logic.values.assignedToFilter).toEqual([7, 9])
            expect((logic.values.hogqlQuery.source as AccountsQuery).assignedToUserIds).toEqual([7, 9])
        })

        it('counts toward activeFilterCount', () => {
            expect(logic.values.activeFilterCount).toBe(0)
            logic.actions.setAssignedToFilter([7])
            expect(logic.values.activeFilterCount).toBe(1)
        })

        it('enabling it clears the unassigned flag', async () => {
            logic.actions.setAllRolesUnassigned(true)
            logic.actions.setAssignedToFilter([7])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.assignedToFilter).toEqual([7])
            expect(logic.values.allRolesUnassigned).toBe(false)
        })

        it('enabling it clears the CSM and AE pickers but keeps the owner filter', async () => {
            logic.actions.setCsmFilter([7])
            logic.actions.setAccountExecutiveFilter([8])
            logic.actions.setAccountOwnerFilter([9])
            logic.actions.setAssignedToFilter([CURRENT_USER_ID])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.assignedToFilter).toEqual([CURRENT_USER_ID])
            expect(logic.values.csmFilter).toEqual([])
            expect(logic.values.accountExecutiveFilter).toEqual([])
            expect(logic.values.accountOwnerFilter).toEqual([9])
        })

        it('enabling the unassigned flag clears the assigned-to filter', async () => {
            logic.actions.setAssignedToFilter([7])
            logic.actions.setAllRolesUnassigned(true)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.allRolesUnassigned).toBe(true)
            expect(logic.values.assignedToFilter).toEqual([])
        })

        it('selecting a CSM clears the assigned-to filter', async () => {
            logic.actions.setAssignedToFilter([CURRENT_USER_ID])
            logic.actions.setCsmFilter([7])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.csmFilter).toEqual([7])
            expect(logic.values.assignedToFilter).toEqual([])
        })

        it('selecting an AE clears the assigned-to filter', async () => {
            logic.actions.setAssignedToFilter([CURRENT_USER_ID])
            logic.actions.setAccountExecutiveFilter([8])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.accountExecutiveFilter).toEqual([8])
            expect(logic.values.assignedToFilter).toEqual([])
        })

        it('selecting an owner leaves the assigned-to filter intact', async () => {
            logic.actions.setAssignedToFilter([CURRENT_USER_ID])
            logic.actions.setAccountOwnerFilter([9])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.accountOwnerFilter).toEqual([9])
            expect(logic.values.assignedToFilter).toEqual([CURRENT_USER_ID])
        })

        it('persists concrete ids in the view hash (shareable, not viewer-relative)', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAssignedToCurrentUser(true)
            }).toFinishAllListeners()
            expect(router.values.hashParams.view).toEqual({ assignedTo: [CURRENT_USER_ID] })
        })

        it('restores the assigned-to filter from the view hash, independent of the viewer', async () => {
            // A link shared by user 7 resolves to user 7's accounts for everyone —
            // the checkbox is unchecked (not the current user) but the filter applies.
            router.actions.push(urls.customerAnalyticsAccounts(), {}, { view: { assignedTo: [7] } })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.assignedToFilter).toEqual([7])
            expect(logic.values.assignedToCurrentUser).toBe(false)
            expect((logic.values.hogqlQuery.source as AccountsQuery).assignedToUserIds).toEqual([7])
        })

        it('restores a legacy mine=true link as the current user', async () => {
            router.actions.push(urls.customerAnalyticsAccounts(), {}, { view: { mine: true } })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.assignedToFilter).toEqual([CURRENT_USER_ID])
            expect(logic.values.assignedToCurrentUser).toBe(true)
        })
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

    describe('url persistence', () => {
        it('writes active filters into the view hash param', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('acme')
                logic.actions.setTagsFilter(['enterprise'])
                logic.actions.setCsmFilter([7])
                logic.actions.setSortOrder({ column: 'name', direction: 'desc' })
                logic.actions.setTileFilter({ tileId: 'tile-1', expression: 'count() > 5' })
            }).toFinishAllListeners()

            expect(router.values.hashParams.view).toEqual({
                search: 'acme',
                tags: ['enterprise'],
                csm: [7],
                sort: { column: 'name', direction: 'desc' },
                tileFilter: { tileId: 'tile-1', expression: 'count() > 5' },
            })
        })

        it('keeps the hash empty for the default view', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTagsFilter(['enterprise'])
                logic.actions.setTagsFilter([])
            }).toFinishAllListeners()

            expect(router.values.hashParams.view).toBeUndefined()
        })

        it('restores filters, sort, and tile filter from the view hash param', async () => {
            const tileFilter = { tileId: 'tile-1', expression: 'count() > 5' }
            router.actions.push(
                urls.customerAnalyticsAccounts(),
                {},
                {
                    view: { search: 'beta', csm: [7], sort: { column: 'name', direction: 'desc' }, tileFilter },
                }
            )
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.searchQuery).toBe('beta')
            expect(logic.values.searchInput).toBe('beta')
            expect(logic.values.csmFilter).toEqual([7])
            expect(logic.values.sortOrder).toEqual({ column: 'name', direction: 'desc' })
            expect(logic.values.tileFilter).toEqual(tileFilter)
        })

        it('coerces a legacy single-number role id from an old shared URL into an array', async () => {
            // URLs shared before the filters became multi-select stored e.g. `csm: 7`.
            router.actions.push(urls.customerAnalyticsAccounts(), {}, { view: { csm: 7, accountExecutive: 9 } })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.csmFilter).toEqual([7])
            expect(logic.values.accountExecutiveFilter).toEqual([9])
        })

        it('restores columns and shields them from a late saved column config', async () => {
            router.actions.push(
                urls.customerAnalyticsAccounts(),
                {},
                {
                    view: { columns: [ACCOUNTS_NAME_COLUMN, 'csm'] },
                }
            )
            await expectLogic(logic).toFinishAllListeners()

            const config = accountsColumnConfigLogic.findMounted()
            expect(config?.values.selectColumns).toEqual([ACCOUNTS_NAME_COLUMN, 'csm'])

            // A saved config arriving after the URL was applied must not clobber the shared view.
            config?.actions.loadSavedColumnConfigurationSuccess({
                id: 'saved-1',
                columns: [ACCOUNTS_NAME_COLUMN, 'account_owner'],
            })
            await expectLogic(config!).toFinishAllListeners()
            expect(config?.values.selectColumns).toEqual([ACCOUNTS_NAME_COLUMN, 'csm'])
        })

        it('applies the saved column config when the URL has no columns', async () => {
            router.actions.push(urls.customerAnalyticsAccounts(), {}, {})
            await expectLogic(logic).toFinishAllListeners()

            const config = accountsColumnConfigLogic.findMounted()
            config?.actions.loadSavedColumnConfigurationSuccess({
                id: 'saved-1',
                columns: [ACCOUNTS_NAME_COLUMN, 'account_owner'],
            })
            await expectLogic(config!).toFinishAllListeners()
            expect(config?.values.selectColumns).toEqual([ACCOUNTS_NAME_COLUMN, 'account_owner'])
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
