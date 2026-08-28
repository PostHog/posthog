import {
    AccountsTableAccountField,
    AccountsTableAccountFieldOperator,
    AccountsTableCustomPropertyOperator,
    AccountsTableSortDirection,
    NodeKind,
} from '~/queries/schema/schema-general'
import { AccountCustomPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { AccountPropertyFilter } from './accountsPropertyFilters'
import {
    AccountsTableQueryPlan,
    BuildAccountsTableQueryPlanInput,
    accountsTableCell,
    buildAccountsTableQueryPlan,
} from './accountsTableQuery'

const RELATIONSHIP_ID = '11111111-2222-3333-4444-555555555555'
const CUSTOM_PROPERTY_ID = '66666666-7777-8888-9999-aaaaaaaaaaaa'

const definition = {
    id: CUSTOM_PROPERTY_ID,
    name: 'MRR',
    display_type: 'currency',
} as CustomPropertyDefinitionApi

function accountFieldFilter(overrides: Partial<AccountPropertyFilter> = {}): AccountPropertyFilter {
    return {
        type: PropertyFilterType.Account,
        key: AccountsTableAccountField.IgnoredAt,
        operator: PropertyOperator.IsSet,
        value: null,
        ...overrides,
    }
}

function customFilter(overrides: Partial<AccountCustomPropertyFilter> = {}): AccountCustomPropertyFilter {
    return {
        type: PropertyFilterType.AccountCustomProperty,
        key: CUSTOM_PROPERTY_ID,
        operator: PropertyOperator.GreaterThan,
        value: 10,
        ...overrides,
    }
}

function queryInput(overrides: Partial<BuildAccountsTableQueryPlanInput> = {}): BuildAccountsTableQueryPlanInput {
    return {
        querySelectColumns: [
            'name',
            'accounts.tags.names AS tag_names',
            'accounts.notebooks.count AS notebook_count',
            `accounts.relationships.values.\`${RELATIONSHIP_ID}\` AS csm`,
        ],
        visibleColumnNames: ['name', 'tag_names', 'notebook_count', 'csm'],
        searchQuery: '',
        tagsFilter: [],
        allRolesUnassigned: false,
        assignedToFilter: [],
        accountIdFilter: null,
        tileFilter: null,
        accountFilters: [],
        customPropertyDefinitionsById: { [CUSTOM_PROPERTY_ID]: definition },
        columnDisplay: {},
        sortOrder: null,
        canSortClientSide: true,
        ...overrides,
    }
}

describe('accountsTableQuery', () => {
    it('translates supported columns, filters, and server-side sorting', () => {
        const plan = buildAccountsTableQueryPlan(
            queryInput({
                searchQuery: ' acme ',
                tagsFilter: ['enterprise'],
                assignedToFilter: [7, 9],
                accountFilters: [customFilter()],
                sortOrder: { column: 'csm', direction: 'desc' },
                canSortClientSide: false,
            })
        )

        expect(plan?.query).toMatchObject({
            kind: NodeKind.AccountsTableQuery,
            columns: [
                { kind: 'account_field', field: AccountsTableAccountField.Name },
                { kind: 'tags' },
                { kind: 'note_count' },
                { kind: 'relationship', definitionId: RELATIONSHIP_ID },
            ],
            filters: [
                { kind: 'search', query: 'acme' },
                { kind: 'tags', tagNames: ['enterprise'] },
                { kind: 'assigned_to', userIds: [7, 9] },
                {
                    kind: 'custom_property',
                    definitionId: CUSTOM_PROPERTY_ID,
                    operator: AccountsTableCustomPropertyOperator.GreaterThan,
                    values: [10],
                },
            ],
            sort: {
                column: { kind: 'relationship', definitionId: RELATIONSHIP_ID },
                direction: AccountsTableSortDirection.Descending,
            },
        })
    })

    it('translates typed native account field filters', () => {
        const plan = buildAccountsTableQueryPlan(
            queryInput({
                accountFilters: [
                    accountFieldFilter(),
                    accountFieldFilter({
                        key: AccountsTableAccountField.CreatedAt,
                        operator: PropertyOperator.IsDateAfter,
                        value: '2026-08-01',
                    }),
                ],
            })
        )

        expect(plan.query.filters).toEqual([
            {
                kind: 'account_field',
                field: AccountsTableAccountField.IgnoredAt,
                operator: AccountsTableAccountFieldOperator.IsSet,
                values: [],
            },
            {
                kind: 'account_field',
                field: AccountsTableAccountField.CreatedAt,
                operator: AccountsTableAccountFieldOperator.DateAfter,
                values: ['2026-08-01'],
            },
        ])
    })

    it('omits incompatible native account field filters', () => {
        const plan = buildAccountsTableQueryPlan(
            queryInput({
                accountFilters: [
                    accountFieldFilter({
                        key: AccountsTableAccountField.Name,
                        operator: PropertyOperator.IsDateAfter,
                        value: '2026-08-01',
                    }),
                ],
            })
        )

        expect(plan.query.filters).toEqual([])
    })

    it('translates saved custom-property history display configuration', () => {
        const plan = buildAccountsTableQueryPlan(
            queryInput({
                querySelectColumns: [
                    'name',
                    `accounts.custom_properties_history.values.\`${CUSTOM_PROPERTY_ID}\` AS cp_value`,
                ],
                visibleColumnNames: ['name', 'cp_value'],
                columnDisplay: { [CUSTOM_PROPERTY_ID]: { mode: 'sparkline', window_days: 30 } },
                sortOrder: { column: 'cp_value', direction: 'asc' },
                canSortClientSide: false,
            })
        )

        expect(plan?.query.columns[1]).toEqual({
            kind: 'custom_property_history',
            definitionId: CUSTOM_PROPERTY_ID,
            windowDays: 30,
        })
        expect(plan?.query.sort).toEqual({
            column: { kind: 'custom_property', definitionId: CUSTOM_PROPERTY_ID },
            direction: AccountsTableSortDirection.Ascending,
        })
    })

    it('uses only the account ID filter for deep-link state', () => {
        const plan = buildAccountsTableQueryPlan(
            queryInput({
                accountIdFilter: RELATIONSHIP_ID,
                searchQuery: 'ignored',
                tagsFilter: ['ignored'],
                allRolesUnassigned: true,
            })
        )

        expect(plan?.query.filters).toEqual([{ kind: 'account_id', accountId: RELATIONSHIP_ID }])
        expect(plan?.query.includeChurned).toBe(true)
        expect(plan?.query.includeIgnored).toBe(true)
    })

    it('drops unsupported columns instead of changing runners', () => {
        const plan = buildAccountsTableQueryPlan(
            queryInput({
                querySelectColumns: ['name', 'arbitrary_hogql()'],
                visibleColumnNames: ['name', 'unsupported'],
            })
        )

        expect(plan.query.columns).toEqual([{ kind: 'account_field', field: 'name' }])
        expect(plan.columns.map((column) => column.visibleName)).toEqual(['name'])
    })

    it('translates a threshold tile into a typed list filter', () => {
        const plan = buildAccountsTableQueryPlan(
            queryInput({
                tileFilter: {
                    tileId: 'tile',
                    filter: {
                        kind: 'custom_property',
                        definitionId: CUSTOM_PROPERTY_ID,
                        operator: AccountsTableCustomPropertyOperator.GreaterThan,
                        values: [1],
                    },
                },
            })
        )

        expect(plan.query.filters).toEqual([
            {
                kind: 'custom_property',
                definitionId: CUSTOM_PROPERTY_ID,
                operator: AccountsTableCustomPropertyOperator.GreaterThan,
                values: [1],
            },
        ])
    })

    it('excludes unset accounts from a not-equal threshold tile', () => {
        const plan = buildAccountsTableQueryPlan(
            queryInput({
                tileFilter: {
                    tileId: 'tile',
                    filter: {
                        kind: 'custom_property',
                        definitionId: CUSTOM_PROPERTY_ID,
                        operator: AccountsTableCustomPropertyOperator.IsNot,
                        values: [1],
                    },
                },
            })
        )

        expect(plan.query.filters).toEqual([
            {
                kind: 'custom_property',
                definitionId: CUSTOM_PROPERTY_ID,
                operator: AccountsTableCustomPropertyOperator.IsSet,
                values: [],
            },
            {
                kind: 'custom_property',
                definitionId: CUSTOM_PROPERTY_ID,
                operator: AccountsTableCustomPropertyOperator.IsNot,
                values: [1],
            },
        ])
    })

    it.each([
        ['regex', 'currency', PropertyOperator.Regex],
        ['contains on a number', 'currency', PropertyOperator.IContains],
        ['comparison on text', 'text', PropertyOperator.GreaterThan],
        ['date comparison on boolean', 'boolean', PropertyOperator.IsDateBefore],
    ])('omits unsupported %s custom property filters', (_, displayType, operator) => {
        const incompatibleDefinition = { ...definition, display_type: displayType } as CustomPropertyDefinitionApi
        const plan = buildAccountsTableQueryPlan(
            queryInput({
                customPropertyDefinitionsById: { [CUSTOM_PROPERTY_ID]: incompatibleDefinition },
                accountFilters: [customFilter({ operator })],
            })
        )

        expect(plan.query.filters).toEqual([])
    })

    it('keeps contains filters for link properties', () => {
        const linkDefinition = { ...definition, display_type: 'link' } as CustomPropertyDefinitionApi
        const plan = buildAccountsTableQueryPlan(
            queryInput({
                customPropertyDefinitionsById: { [CUSTOM_PROPERTY_ID]: linkDefinition },
                accountFilters: [customFilter({ operator: PropertyOperator.IContains, value: 'example.com' })],
            })
        )

        expect(plan.query.filters).toEqual([
            {
                kind: 'custom_property',
                definitionId: CUSTOM_PROPERTY_ID,
                operator: AccountsTableCustomPropertyOperator.Contains,
                values: ['example.com'],
            },
        ])
    })

    it('reads cells directly from keyed rows', () => {
        const plan = buildAccountsTableQueryPlan(queryInput()) as AccountsTableQueryPlan
        const row = {
            id: 'account-id',
            name: 'Acme',
            externalId: 'acme-1',
            accountFields: { name: 'Acme' },
            tags: ['enterprise'],
            noteCount: 2,
            relationships: { [RELATIONSHIP_ID]: [42] },
            customProperties: {},
            customPropertyHistory: {},
        }

        expect(plan.columns.map((column) => accountsTableCell(row, column.visibleName, plan))).toEqual([
            { id: 'account-id', name: 'Acme', external_id: 'acme-1' },
            ['enterprise'],
            2,
            [42],
        ])
    })
})
