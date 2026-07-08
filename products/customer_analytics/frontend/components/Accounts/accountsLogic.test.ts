import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { AccountsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { UserBasicType, UserType } from '~/types'

import {
    accountRelationshipDefinitionsList,
    accountsRelationshipsCreate,
    accountsRelationshipsEndCreate,
    accountsRelationshipsList,
    customPropertyDefinitionsList,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountRelationshipApi,
    AccountRelationshipDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import {
    ACCOUNTS_HOGQL_DEFAULT_SELECT,
    ACCOUNTS_NAME_COLUMN,
    accountsColumnConfigLogic,
    relationshipAlias,
} from './accountsColumnConfigLogic'
import { DEFAULT_ACCOUNT_TAB, accountsExpansionLogic } from './accountsExpansionLogic'
import { accountsLogic, savingRoleKey } from './accountsLogic'

// `hogqlQuery.source` is typed as the full DataTableNode source union; this logic
// always produces an AccountsQuery, so narrow once for the orderBy assertions.
const orderByOf = (source: unknown): AccountsQuery['orderBy'] => (source as AccountsQuery).orderBy

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    // Keep the real module for everything else — connected logics call other generated
    // functions on mount, and an absent export makes their loaders throw on every test.
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountRelationshipDefinitionsList: jest.fn(),
    customPropertyDefinitionsList: jest.fn(),
    accountsRelationshipsCreate: jest.fn(),
    accountsRelationshipsEndCreate: jest.fn(),
    accountsRelationshipsList: jest.fn(),
}))

const mockDefinitionsList = accountRelationshipDefinitionsList as jest.MockedFunction<
    typeof accountRelationshipDefinitionsList
>
const mockCustomPropertiesList = customPropertyDefinitionsList as jest.MockedFunction<
    typeof customPropertyDefinitionsList
>
const mockRelationshipsCreate = accountsRelationshipsCreate as jest.MockedFunction<typeof accountsRelationshipsCreate>
const mockRelationshipsEnd = accountsRelationshipsEndCreate as jest.MockedFunction<
    typeof accountsRelationshipsEndCreate
>
const mockRelationshipsList = accountsRelationshipsList as jest.MockedFunction<typeof accountsRelationshipsList>

const DEFINITIONS: AccountRelationshipDefinitionApi[] = [
    { id: 'def-csm', name: 'CSM', description: null, is_single_holder: true },
    { id: 'def-ae', name: 'Account executive', description: null, is_single_holder: true },
    { id: 'def-owner', name: 'Account owner', description: null, is_single_holder: true },
]

const buildRelationship = (overrides: Partial<AccountRelationshipApi> = {}): AccountRelationshipApi => ({
    id: 'rel-1',
    definition: DEFINITIONS[0],
    user: { id: 42, email: 'alex@example.com' },
    started_at: '2026-01-01T00:00:00Z',
    ended_at: null,
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

    beforeEach(async () => {
        initKeaTests()
        jest.resetAllMocks()
        // accountsLogic connects to the (localStorage-persisted) shared scene logic;
        // clear it so a "mine only" write in one test can't leak into the next.
        localStorage.clear()
        mockDefinitionsList.mockResolvedValue({ count: DEFINITIONS.length, results: DEFINITIONS })
        mockCustomPropertiesList.mockResolvedValue({ count: 0, results: [] })
        logic = accountsLogic()
        logic.mount()
        // Legacy role columns only resolve into the query once definitions load.
        await expectLogic(accountsColumnConfigLogic.findMounted()!).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        localStorage.clear()
    })

    it('starts with empty filters', () => {
        expect(logic.values.searchQuery).toBe('')
        expect(logic.values.tagsFilter).toEqual([])
        expect(logic.values.allRolesUnassigned).toBe(false)
        expect(logic.values.assignedToFilter).toEqual([])
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

    it('keeps the overview tile metrics off the list query so it loads independently', () => {
        const source = logic.values.hogqlQuery.source as AccountsQuery
        expect(source.metrics).toBeUndefined()
    })

    it('exposes the overview tile metrics on a separate metrics-only query (no select)', () => {
        const metricsQuery = logic.values.metricsQuery as AccountsQuery
        expect(metricsQuery.metrics).toEqual(['count()'])
        expect(metricsQuery.select).toBeUndefined()
    })

    it('setAllRolesUnassigned toggles the flag', () => {
        logic.actions.setAllRolesUnassigned(true)
        expect(logic.values.allRolesUnassigned).toBe(true)
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

        it('enabling the unassigned flag clears the assigned-to filter', async () => {
            logic.actions.setAssignedToFilter([7])
            logic.actions.setAllRolesUnassigned(true)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.allRolesUnassigned).toBe(true)
            expect(logic.values.assignedToFilter).toEqual([])
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

        // The "mine only" choice is held in the shared scene logic so it survives a
        // switch to the Notes tab. These guard the two-way link between the accounts
        // assigned-to filter and that shared toggle.
        describe('shared "mine only" toggle', () => {
            it('toggling "My accounts" writes the shared toggle', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setAssignedToCurrentUser(true)
                }).toFinishAllListeners()
                expect(customerAnalyticsSceneLogic.values.mineOnly).toBe(true)

                await expectLogic(logic, () => {
                    logic.actions.setAssignedToCurrentUser(false)
                }).toFinishAllListeners()
                expect(customerAnalyticsSceneLogic.values.mineOnly).toBe(false)
            })

            it('picking explicit assignees clears the shared toggle', async () => {
                customerAnalyticsSceneLogic.actions.setMineOnly(true)
                await expectLogic(logic, () => {
                    logic.actions.setAssignedToFilter([7])
                }).toFinishAllListeners()
                expect(customerAnalyticsSceneLogic.values.mineOnly).toBe(false)
            })

            it('restores "my accounts" from the shared toggle when the URL has no view hash', async () => {
                customerAnalyticsSceneLogic.actions.setMineOnly(true)
                router.actions.push(urls.customerAnalyticsAccounts())
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.assignedToFilter).toEqual([CURRENT_USER_ID])
                expect(logic.values.assignedToCurrentUser).toBe(true)
            })

            it('an explicit shared link still wins over the shared toggle', async () => {
                customerAnalyticsSceneLogic.actions.setMineOnly(true)
                router.actions.push(urls.customerAnalyticsAccounts(), {}, { view: { assignedTo: [7] } })
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.assignedToFilter).toEqual([7])
                expect(customerAnalyticsSceneLogic.values.mineOnly).toBe(false)
            })

            // Regression: on a fresh load the logic can run URL restore before userLogic
            // resolves the user (currentUserId null), so the persisted choice can't be applied
            // then. The user resolving later must apply it, without clearing the preference.
            it('applies the persisted "my accounts" choice when the user resolves after restore', async () => {
                customerAnalyticsSceneLogic.actions.setMineOnly(true)
                expect(logic.values.assignedToFilter).toEqual([])

                await expectLogic(logic, () => {
                    userLogic.actions.loadUserSuccess(buildUser({ id: CURRENT_USER_ID }) as unknown as UserType)
                }).toFinishAllListeners()

                expect(logic.values.assignedToFilter).toEqual([CURRENT_USER_ID])
                expect(customerAnalyticsSceneLogic.values.mineOnly).toBe(true)
            })

            it('the user resolving does not override an explicit assigned-to from the URL', async () => {
                router.actions.push(urls.customerAnalyticsAccounts(), {}, { view: { assignedTo: [7] } })
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    userLogic.actions.loadUserSuccess(buildUser({ id: CURRENT_USER_ID }) as unknown as UserType)
                }).toFinishAllListeners()

                expect(logic.values.assignedToFilter).toEqual([7])
            })
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
            expect(orderByOf(logic.values.hogqlQuery.source)).toEqual(['csm'])
        })

        it('arbitrary column sorts by its alias directly', () => {
            logic.actions.toggleSort('name')
            expect(orderByOf(logic.values.hogqlQuery.source)).toEqual(['name'])
            logic.actions.toggleSort('name')
            expect(orderByOf(logic.values.hogqlQuery.source)).toEqual(['name DESC'])
        })

        it('skips the orderBy when the sorted role column has no matching definition', () => {
            logic.actions.toggleSort('csm')
            accountsColumnConfigLogic.findMounted()?.actions.loadRelationshipDefinitionsSuccess([])
            expect(orderByOf(logic.values.hogqlQuery.source)).toBeUndefined()
        })
    })

    describe('selectColumns', () => {
        it('defaults to the base columns plus one column per definition, name column included', () => {
            const config = accountsColumnConfigLogic.findMounted()
            expect(config?.values.selectColumns).toEqual([
                ...ACCOUNTS_HOGQL_DEFAULT_SELECT,
                'csm',
                'account_executive',
                'account_owner',
            ])
            expect(config?.values.selectColumns).toContain(ACCOUNTS_NAME_COLUMN)
        })

        it('translates legacy role columns through the relationships lazy join in the query select', () => {
            const source = logic.values.hogqlQuery.source as AccountsQuery
            expect(source.select).toEqual([
                ACCOUNTS_NAME_COLUMN,
                'accounts.tags.names AS tag_names',
                'accounts.notebooks.count AS notebook_count',
                'accounts.relationships.values.`def-csm` AS csm',
                'accounts.relationships.values.`def-ae` AS account_executive',
                'accounts.relationships.values.`def-owner` AS account_owner',
            ])
        })

        it('drops legacy role columns from the query when no matching definition exists', () => {
            accountsColumnConfigLogic.findMounted()?.actions.loadRelationshipDefinitionsSuccess([])
            const source = logic.values.hogqlQuery.source as AccountsQuery
            expect(source.select).toEqual([
                ACCOUNTS_NAME_COLUMN,
                'accounts.tags.names AS tag_names',
                'accounts.notebooks.count AS notebook_count',
            ])
            expect(logic.values.visibleColumnNames).toEqual([ACCOUNTS_NAME_COLUMN, 'tag_names', 'notebook_count'])
        })

        it('materializes pristine defaults into one column per definition once definitions load', () => {
            const config = accountsColumnConfigLogic.findMounted()!
            config.actions.loadRelationshipDefinitionsSuccess([
                ...DEFINITIONS,
                { id: 'def-os', name: 'Onboarding specialist', description: null, is_single_holder: true },
            ])
            expect(config.values.selectColumns).toEqual([
                ...ACCOUNTS_HOGQL_DEFAULT_SELECT,
                'csm',
                'account_executive',
                'account_owner',
                `accounts.relationships.values.\`def-os\` AS ${relationshipAlias('def-os')}`,
            ])
        })

        it('leaves customized columns alone when definitions load', () => {
            const config = accountsColumnConfigLogic.findMounted()!
            config.actions.setSelectColumns([ACCOUNTS_NAME_COLUMN, 'csm'])
            config.actions.loadRelationshipDefinitionsSuccess([
                ...DEFINITIONS,
                { id: 'def-os', name: 'Onboarding specialist', description: null, is_single_holder: true },
            ])
            expect(config.values.selectColumns).toEqual([ACCOUNTS_NAME_COLUMN, 'csm'])
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
                logic.actions.setAssignedToFilter([7])
                logic.actions.setSortOrder({ column: 'name', direction: 'desc' })
                logic.actions.setTileFilter({ tileId: 'tile-1', expression: 'count() > 5' })
            }).toFinishAllListeners()

            expect(router.values.hashParams.view).toEqual({
                search: 'acme',
                tags: ['enterprise'],
                assignedTo: [7],
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
                    view: { search: 'beta', assignedTo: [7], sort: { column: 'name', direction: 'desc' }, tileFilter },
                }
            )
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.searchQuery).toBe('beta')
            expect(logic.values.searchInput).toBe('beta')
            expect(logic.values.assignedToFilter).toEqual([7])
            expect(logic.values.sortOrder).toEqual({ column: 'name', direction: 'desc' })
            expect(logic.values.tileFilter).toEqual(tileFilter)
        })

        it('coerces a malformed scalar assignedTo from the view hash into an array', async () => {
            // normalizeRoleFilter defends the array-shaped filter against a stray
            // scalar in the hash (hand-edited or stale link) so .length/.map stay safe.
            router.actions.push(urls.customerAnalyticsAccounts(), {}, { view: { assignedTo: 7 } })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.assignedToFilter).toEqual([7])
        })

        it('restores columns from the view hash param', async () => {
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
        })
    })

    describe('deep link (path route)', () => {
        // `/customer_analytics/accounts/:accountId/:tab` filters the list to one account and opens a tab.
        const ACCOUNT_ID = '0190da51-0b0e-7000-8000-000000000001'

        const filterExpressionOf = (source: unknown): string | undefined => (source as AccountsQuery).filterExpression

        it('filters the list to the account, expands it, and opens the requested tab', async () => {
            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID, 'usage'))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.accountIdFilter).toBe(ACCOUNT_ID)
            expect(filterExpressionOf(logic.values.hogqlQuery.source)).toContain(`toString(id) = '${ACCOUNT_ID}'`)
            const expansion = accountsExpansionLogic.findMounted()
            expect(expansion?.values.expandedAccountIds).toContain(ACCOUNT_ID)
            expect(expansion?.values.activeTabByAccount[ACCOUNT_ID]).toBe('usage')
        })

        it('defaults the tab when the path omits it', async () => {
            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID))
            await expectLogic(logic).toFinishAllListeners()

            const expansion = accountsExpansionLogic.findMounted()
            expect(expansion?.values.activeTabByAccount[ACCOUNT_ID]).toBe(DEFAULT_ACCOUNT_TAB)
        })

        it('falls back to the default tab for an unknown tab', async () => {
            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID, 'bogus'))
            await expectLogic(logic).toFinishAllListeners()

            const expansion = accountsExpansionLogic.findMounted()
            expect(expansion?.values.activeTabByAccount[ACCOUNT_ID]).toBe(DEFAULT_ACCOUNT_TAB)
        })

        it('ignores a non-UUID account id', async () => {
            router.actions.push(urls.customerAnalyticsAccount('not-a-uuid', 'usage'))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.accountIdFilter).toBeNull()
        })

        it('clears the account filter when returning to the bare list', async () => {
            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID, 'usage'))
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.accountIdFilter).toBe(ACCOUNT_ID)

            router.actions.push(urls.customerAnalyticsAccounts())
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.accountIdFilter).toBeNull()
        })
    })

    describe('updateAccountRole', () => {
        it('assigns via the relationships API and masks the cell with an override', async () => {
            const user = buildUser()
            mockRelationshipsCreate.mockResolvedValue(buildRelationship())

            logic.actions.updateAccountRole('acc-1', 'csm', user)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockRelationshipsCreate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'acc-1', {
                definition: 'def-csm',
                user: user.id,
            })
            expect(logic.values.relationshipOverrides[savingRoleKey('acc-1', 'csm')]).toEqual([user.id])
        })

        it('unassigning ends only the active assignments of that definition', async () => {
            mockRelationshipsList.mockResolvedValue([
                buildRelationship({ id: 'rel-csm', definition: DEFINITIONS[0] }),
                buildRelationship({ id: 'rel-ae', definition: DEFINITIONS[1] }),
            ])
            mockRelationshipsEnd.mockResolvedValue(
                buildRelationship({ id: 'rel-csm', ended_at: '2026-01-02T00:00:00Z' })
            )

            logic.actions.updateAccountRole('acc-1', 'csm', null)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockRelationshipsEnd).toHaveBeenCalledTimes(1)
            expect(mockRelationshipsEnd).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'acc-1', 'rel-csm')
            expect(logic.values.relationshipOverrides[savingRoleKey('acc-1', 'csm')]).toEqual([])
        })

        it('flips savingRoles during the in-flight window', async () => {
            const key = savingRoleKey('acc-1', 'account_executive')
            let resolveCreate!: (value: AccountRelationshipApi) => void
            mockRelationshipsCreate.mockReturnValueOnce(
                new Promise<AccountRelationshipApi>((resolve) => {
                    resolveCreate = resolve
                })
            )

            logic.actions.updateAccountRole('acc-1', 'account_executive', buildUser())
            await new Promise<void>((r) => setTimeout(r, 0))
            expect(logic.values.savingRoles[key]).toBe(true)
            expect(logic.values.isRoleSaving('acc-1', 'account_executive')).toBe(true)

            resolveCreate(buildRelationship())
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.savingRoles[key]).toBeUndefined()
            expect(logic.values.isRoleSaving('acc-1', 'account_executive')).toBe(false)
        })

        it('leaves overrides untouched on failure', async () => {
            mockRelationshipsCreate.mockRejectedValueOnce(new Error('boom'))

            logic.actions.updateAccountRole('acc-1', 'account_owner', buildUser())
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.relationshipOverrides[savingRoleKey('acc-1', 'account_owner')]).toBeUndefined()
            expect(logic.values.isRoleSaving('acc-1', 'account_owner')).toBe(false)
        })

        it('is a no-op while a save for the same role is already in flight', async () => {
            let resolveFirst!: (value: AccountRelationshipApi) => void
            mockRelationshipsCreate.mockReturnValueOnce(
                new Promise<AccountRelationshipApi>((resolve) => {
                    resolveFirst = resolve
                })
            )

            logic.actions.updateAccountRole('acc-1', 'csm', buildUser({ id: 1, email: 'first@example.com' }))
            await new Promise<void>((r) => setTimeout(r, 0))
            logic.actions.updateAccountRole('acc-1', 'csm', buildUser({ id: 2, email: 'second@example.com' }))
            await new Promise<void>((r) => setTimeout(r, 0))

            expect(mockRelationshipsCreate).toHaveBeenCalledTimes(1)

            resolveFirst(buildRelationship())
            await expectLogic(logic).toFinishAllListeners()
        })
    })
})
