import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    AccountsTableAccountField,
    AccountsTableAccountFieldOperator,
    AccountsTableCustomPropertyOperator,
    type AccountsTableQuery,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator, type UserBasicType, type UserType } from '~/types'

import {
    accountRelationshipDefinitionsList,
    accountsPartialUpdate,
    accountsRelationshipsCreate,
    accountsRelationshipsEndCreate,
    accountsRelationshipsList,
    customPropertyDefinitionsList,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountApi,
    AccountRelationshipApi,
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import {
    ACCOUNTS_DEFAULT_COLUMNS,
    ACCOUNTS_NAME_COLUMN,
    accountsColumnConfigLogic,
    relationshipAlias,
} from './accountsColumnConfigLogic'
import { DEFAULT_ACCOUNT_TAB, accountsExpansionLogic } from './accountsExpansionLogic'
import { accountsLogic, savingRoleKey } from './accountsLogic'
import { AccountsEvents } from './constants'

const assignedToFilterOf = (query: AccountsTableQuery | null): number[] | undefined =>
    query?.filters?.find((filter) => filter.kind === 'assigned_to')?.userIds

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    // Keep the real module for everything else — connected logics call other generated
    // functions on mount, and an absent export makes their loaders throw on every test.
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountRelationshipDefinitionsList: jest.fn(),
    customPropertyDefinitionsList: jest.fn(),
    accountsPartialUpdate: jest.fn(),
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
const mockPartialUpdate = accountsPartialUpdate as jest.MockedFunction<typeof accountsPartialUpdate>

const CSM_DEFINITION_ID = '11111111-2222-3333-4444-555555555555'
const AE_DEFINITION_ID = '66666666-7777-8888-9999-aaaaaaaaaaaa'
const OWNER_DEFINITION_ID = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff'
const TILE_FILTER = {
    tileId: 'tile-1',
    filter: {
        kind: 'custom_property' as const,
        definitionId: CSM_DEFINITION_ID,
        operator: AccountsTableCustomPropertyOperator.GreaterThan,
        values: [5],
    },
}

const DEFINITIONS: AccountRelationshipDefinitionApi[] = [
    { id: CSM_DEFINITION_ID, name: 'CSM', description: null, is_single_holder: true },
    { id: AE_DEFINITION_ID, name: 'Account executive', description: null, is_single_holder: true },
    { id: OWNER_DEFINITION_ID, name: 'Account owner', description: null, is_single_holder: true },
]

const buildRelationship = (overrides: Partial<AccountRelationshipApi> = {}): AccountRelationshipApi => ({
    id: 'rel-1',
    definition: DEFINITIONS[0],
    user: { id: 42, email: 'alex@example.com' },
    started_at: '2026-01-01T00:00:00Z',
    ended_at: null,
    ...overrides,
})

const buildAccount = (overrides: Partial<AccountApi> = {}): AccountApi => ({
    id: 'acc-1',
    name: 'Acme',
    tags: [],
    notebooks: [],
    ignored_at: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
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

    it('runs the list and overview through typed Postgres queries', () => {
        const source = logic.values.accountsQuerySource as AccountsTableQuery
        expect(source.kind).toBe('AccountsTableQuery')
        expect(source.columns).toEqual([
            { kind: 'account_field', field: 'name' },
            { kind: 'tags' },
            { kind: 'note_count' },
            { kind: 'relationship', definitionId: CSM_DEFINITION_ID },
            { kind: 'relationship', definitionId: AE_DEFINITION_ID },
            { kind: 'relationship', definitionId: OWNER_DEFINITION_ID },
        ])
        expect(logic.values.metricsQuery).toMatchObject({
            kind: 'AccountsTableQuery',
            columns: [],
            metrics: [{ kind: 'count' }],
        })
    })

    it('keeps the DataTable on the typed source', () => {
        expect(logic.values.accountsDataTableQuery.source.kind).toBe('AccountsTableQuery')
        expect(logic.values.accountsDataTableQuery.columns).toEqual(logic.values.visibleColumnNames)
    })

    it('drops unsupported saved columns instead of falling back to HogQL', () => {
        accountsColumnConfigLogic
            .findMounted()!
            .actions.setSelectColumns([...logic.values.selectColumns, 'arbitrary_hogql()'])

        expect(logic.values.accountsQuerySource?.kind).toBe('AccountsTableQuery')
        expect(logic.values.accountsDataTableQuery.columns).not.toContain('arbitrary_hogql()')
    })

    it('removes restored unsupported custom-property filters', () => {
        logic.actions.loadCustomPropertyDefinitionsSuccess([
            {
                id: CSM_DEFINITION_ID,
                name: 'Plan',
                display_type: 'currency',
            } as CustomPropertyDefinitionApi,
        ])
        logic.actions.updateAccountFilters([
            {
                type: PropertyFilterType.AccountCustomProperty,
                key: CSM_DEFINITION_ID,
                operator: PropertyOperator.Regex,
                value: 'enterprise.*',
            },
        ])

        expect(logic.values.accountFilters).toEqual([])
        expect(logic.values.activeFilterCount).toBe(0)
    })

    it('adds native account filters to the query and shareable view state', () => {
        logic.actions.updateAccountFilters([
            {
                type: PropertyFilterType.Account,
                key: AccountsTableAccountField.IgnoredAt,
                label: 'Ignored at',
                operator: PropertyOperator.IsSet,
                value: null,
            },
        ])

        expect(logic.values.accountsQuerySource?.filters).toContainEqual({
            kind: 'account_field',
            field: AccountsTableAccountField.IgnoredAt,
            operator: AccountsTableAccountFieldOperator.IsSet,
            values: [],
        })
        expect(logic.values.viewUrlState.customProperties).toEqual(logic.values.accountFilters)
    })

    it('captures native filter shape without its field or value', () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()

        logic.actions.updateAccountFilters([
            {
                type: PropertyFilterType.Account,
                key: AccountsTableAccountField.ExternalId,
                operator: PropertyOperator.Exact,
                value: 'private-value',
            },
        ])

        expect(capture).toHaveBeenCalledWith(AccountsEvents.FilterChanged, {
            filter_type: 'account_field',
            field_kind: 'account_field',
            operator: PropertyOperator.Exact,
            filter_count: 1,
            is_cleared: false,
            active_filter_count: 1,
        })
        expect(capture.mock.calls.at(-1)?.[1]).not.toHaveProperty('key')
        expect(capture.mock.calls.at(-1)?.[1]).not.toHaveProperty('value')
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

    it('withholds the list and metrics queries until relationship definitions settle', async () => {
        logic.unmount()
        let resolveDefinitions: (value: { count: number; results: AccountRelationshipDefinitionApi[] }) => void
        mockDefinitionsList.mockReturnValue(new Promise((resolve) => (resolveDefinitions = resolve)))
        logic = accountsLogic()
        logic.mount()

        expect(logic.values.accountsQuerySource).toBeNull()
        expect(logic.values.metricsQuery).toBeNull()

        resolveDefinitions!({ count: DEFINITIONS.length, results: DEFINITIONS })
        await expectLogic(accountsColumnConfigLogic.findMounted()!).toFinishAllListeners()

        expect(logic.values.accountsQuerySource?.kind).toBe('AccountsTableQuery')
        expect(logic.values.metricsQuery).not.toBeNull()
    })

    it('keeps overview metrics off the list query', () => {
        expect(logic.values.accountsQuerySource?.metrics).toBeUndefined()
    })

    it('exposes overview metrics on a separate metrics-only query', () => {
        expect(logic.values.metricsQuery?.metrics).toEqual([{ kind: 'count' }])
        expect(logic.values.metricsQuery?.columns).toEqual([])
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
            expect(assignedToFilterOf(logic.values.accountsQuerySource)).toBeUndefined()
        })

        it('the "My accounts" checkbox resolves to the current user id', () => {
            logic.actions.setAssignedToCurrentUser(true)
            expect(logic.values.assignedToFilter).toEqual([CURRENT_USER_ID])
            expect(logic.values.assignedToCurrentUser).toBe(true)
            expect(assignedToFilterOf(logic.values.accountsQuerySource)).toEqual([CURRENT_USER_ID])
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
            expect(assignedToFilterOf(logic.values.accountsQuerySource)).toBeUndefined()
        })

        it('the Assigned to picker accepts explicit ids', () => {
            logic.actions.setAssignedToFilter([7, 9])
            expect(logic.values.assignedToFilter).toEqual([7, 9])
            expect(assignedToFilterOf(logic.values.accountsQuerySource)).toEqual([7, 9])
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
            expect(assignedToFilterOf(logic.values.accountsQuerySource)).toEqual([7])
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
        it('adds a typed server-side sort after pagination', () => {
            logic.actions.listLoadNextData()
            logic.actions.toggleSort('notebook_count')

            expect(logic.values.accountsQuerySource?.sort).toEqual({
                column: { kind: 'note_count' },
                direction: 'asc',
            })
        })

        it('sorts a fully loaded page in the browser without changing the query', () => {
            logic.actions.toggleSort('notebook_count')

            expect(logic.values.accountsQuerySource?.sort).toBeUndefined()
            expect(logic.values.sortedRowsTransformer).toEqual(expect.any(Function))
        })
    })

    describe('selectColumns', () => {
        it('defaults to the base columns plus one column per definition, name column included', () => {
            const config = accountsColumnConfigLogic.findMounted()
            expect(config?.values.selectColumns).toEqual([
                ...ACCOUNTS_DEFAULT_COLUMNS,
                'csm',
                'account_executive',
                'account_owner',
            ])
            expect(config?.values.selectColumns).toContain(ACCOUNTS_NAME_COLUMN)
        })

        it('translates legacy role columns into typed relationship columns', () => {
            expect(logic.values.accountsQuerySource?.columns).toEqual([
                { kind: 'account_field', field: 'name' },
                { kind: 'tags' },
                { kind: 'note_count' },
                { kind: 'relationship', definitionId: CSM_DEFINITION_ID },
                { kind: 'relationship', definitionId: AE_DEFINITION_ID },
                { kind: 'relationship', definitionId: OWNER_DEFINITION_ID },
            ])
        })

        it('drops legacy role columns from the query when no matching definition exists', () => {
            accountsColumnConfigLogic.findMounted()?.actions.loadRelationshipDefinitionsSuccess([])
            expect(logic.values.accountsQuerySource?.columns).toEqual([
                { kind: 'account_field', field: 'name' },
                { kind: 'tags' },
                { kind: 'note_count' },
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
                ...ACCOUNTS_DEFAULT_COLUMNS,
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
                logic.actions.setTileFilter(TILE_FILTER)
            }).toFinishAllListeners()

            expect(router.values.hashParams.view).toEqual({
                search: 'acme',
                tags: ['enterprise'],
                assignedTo: [7],
                sort: { column: 'name', direction: 'desc' },
                tileFilter: TILE_FILTER,
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
            const tileFilter = TILE_FILTER
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

        it('translates restored URL state into the Postgres query', async () => {
            router.actions.push(
                urls.customerAnalyticsAccounts(),
                {},
                {
                    view: {
                        search: 'acme',
                        tags: ['enterprise'],
                        assignedTo: [7],
                        columns: [ACCOUNTS_NAME_COLUMN, 'csm'],
                    },
                }
            )
            await expectLogic(logic).toFinishAllListeners()

            const source = logic.values.accountsQuerySource as AccountsTableQuery
            expect(source.kind).toBe('AccountsTableQuery')
            expect(source.columns).toEqual([
                { kind: 'account_field', field: 'name' },
                { kind: 'relationship', definitionId: CSM_DEFINITION_ID },
            ])
            expect(source.filters).toEqual([
                { kind: 'search', query: 'acme' },
                { kind: 'tags', tagNames: ['enterprise'] },
                { kind: 'assigned_to', userIds: [7] },
            ])
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

        const accountIdFilterOf = (query: AccountsTableQuery | null): string | undefined =>
            query?.filters?.find((filter) => filter.kind === 'account_id')?.accountId

        it('filters the list to the account, expands it, and opens the requested tab', async () => {
            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID, 'usage'))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.accountIdFilter).toBe(ACCOUNT_ID)
            expect(accountIdFilterOf(logic.values.accountsQuerySource)).toBe(ACCOUNT_ID)
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

        it('resolves to the account even when the viewer has filters of their own', async () => {
            logic.actions.setSearchQuery('something else')
            logic.actions.setAssignedToFilter([99])

            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.accountsQuerySource?.filters).toEqual([{ kind: 'account_id', accountId: ACCOUNT_ID }])
        })

        it('survives a view-state restore rewriting the URL', async () => {
            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID, 'usage'))
            await expectLogic(logic).toFinishAllListeners()
            const deepLinkPath = router.values.location.pathname

            // Landing on a deep link, the saved-view restore and the default-column upgrade both
            // dispatch the setters that mirror view state into the URL. They must not rewrite the
            // path, or the link bounces to the unfiltered list before the user sees the account.
            accountsColumnConfigLogic.findMounted()!.actions.setSelectColumns([ACCOUNTS_NAME_COLUMN, 'csm'])
            await expectLogic(logic).toFinishAllListeners()

            expect(router.values.location.pathname).toBe(deepLinkPath)
            expect(logic.values.accountIdFilter).toBe(ACCOUNT_ID)
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
                definition: CSM_DEFINITION_ID,
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

    describe('updateAccountTags', () => {
        it('masks the cell optimistically and collapses an editing burst into one PATCH with the final list', async () => {
            mockPartialUpdate.mockResolvedValue(buildAccount({ tags: ['vip', 'churn-risk'] }))

            logic.actions.updateAccountTags('acc-1', ['vip'])
            expect(logic.values.tagOverrides['acc-1']).toEqual(['vip'])
            logic.actions.updateAccountTags('acc-1', ['vip', 'churn-risk'])
            expect(logic.values.tagOverrides['acc-1']).toEqual(['vip', 'churn-risk'])
            await expectLogic(logic).toFinishAllListeners()

            expect(mockPartialUpdate).toHaveBeenCalledTimes(1)
            expect(mockPartialUpdate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'acc-1', {
                tags: ['vip', 'churn-risk'],
            })
        })

        it('reverts the optimistic override and clears saving on failure', async () => {
            mockPartialUpdate.mockRejectedValueOnce(new Error('boom'))

            logic.actions.updateAccountTags('acc-1', ['vip'])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.tagOverrides['acc-1']).toBeUndefined()
            expect(logic.values.isTagsSaving('acc-1')).toBe(false)
        })
    })

    describe('addTagToFilter', () => {
        it('compounds clicked tags into the filter and ignores tags already filtered', async () => {
            logic.actions.addTagToFilter('vip')
            logic.actions.addTagToFilter('churn-risk')
            logic.actions.addTagToFilter('vip')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.tagsFilter).toEqual(['vip', 'churn-risk'])
        })
    })
})
