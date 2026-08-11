import {
    AccountsTableAccountField,
    AccountsTableCustomPropertyOperator,
    AccountsTableSortDirection,
    NodeKind,
} from '~/queries/schema/schema-general'
import { AccountCustomPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    AccountsTableQueryPlan,
    BuildAccountsTableQueryPlanInput,
    accountsTableRowsToLegacyRows,
    buildAccountsTableQueryPlan,
} from './accountsTableQuery'

const RELATIONSHIP_ID = '11111111-2222-3333-4444-555555555555'
const CUSTOM_PROPERTY_ID = '66666666-7777-8888-9999-aaaaaaaaaaaa'

const definition = {
    id: CUSTOM_PROPERTY_ID,
    name: 'MRR',
    display_type: 'currency',
} as CustomPropertyDefinitionApi

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
        customPropertyFilters: [],
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
                customPropertyFilters: [customFilter()],
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
    })

    it.each([
        ['tile filter', { tileFilter: { tileId: 'tile', expression: 'count > 1' } }],
        [
            'unsupported column',
            { querySelectColumns: ['name', 'arbitrary_hogql()'], visibleColumnNames: ['name', 'x'] },
        ],
        ['misaligned columns', { querySelectColumns: ['name'], visibleColumnNames: ['name', 'extra'] }],
    ])('falls back to HogQL for %s', (_, overrides) => {
        expect(buildAccountsTableQueryPlan(queryInput(overrides))).toBeNull()
    })

    it.each([
        ['regex', 'currency', PropertyOperator.Regex],
        ['contains on a number', 'currency', PropertyOperator.IContains],
        ['comparison on text', 'text', PropertyOperator.GreaterThan],
        ['date comparison on boolean', 'boolean', PropertyOperator.IsDateBefore],
    ])('falls back to HogQL for %s custom property filters', (_, displayType, operator) => {
        const incompatibleDefinition = { ...definition, display_type: displayType } as CustomPropertyDefinitionApi

        expect(
            buildAccountsTableQueryPlan(
                queryInput({
                    customPropertyDefinitionsById: { [CUSTOM_PROPERTY_ID]: incompatibleDefinition },
                    customPropertyFilters: [customFilter({ operator })],
                })
            )
        ).toBeNull()
    })

    it('translates custom property values and history into positional cells', () => {
        const plan = buildAccountsTableQueryPlan(
            queryInput({
                querySelectColumns: [
                    'name',
                    `accounts.custom_properties.values.\`${CUSTOM_PROPERTY_ID}\` AS cp_value`,
                    `accounts.custom_properties_history.values.\`${CUSTOM_PROPERTY_ID}\` AS cp_history`,
                ],
                visibleColumnNames: ['name', 'cp_value', 'cp_history'],
                columnDisplay: { [CUSTOM_PROPERTY_ID]: { mode: 'trend', window_days: 30 } },
            })
        ) as AccountsTableQueryPlan

        const rows = accountsTableRowsToLegacyRows(
            [
                {
                    id: 'account-id',
                    name: 'Acme',
                    accountFields: { name: 'Acme' },
                    relationships: {},
                    customProperties: { [CUSTOM_PROPERTY_ID]: 42 },
                    customPropertyHistory: {
                        [CUSTOM_PROPERTY_ID]: [{ timestamp: '2026-01-01T00:00:00Z', value: 40 }],
                    },
                },
            ],
            plan
        )

        expect(rows).toEqual([[{ id: 'account-id', name: 'Acme', external_id: null }, 42, [[1767225600, 40]]]])
    })

    it('translates keyed Postgres rows into the positional table response', () => {
        const plan = buildAccountsTableQueryPlan(queryInput()) as AccountsTableQueryPlan
        const rows = accountsTableRowsToLegacyRows(
            [
                {
                    id: 'account-id',
                    name: 'Acme',
                    externalId: 'acme-1',
                    accountFields: { name: 'Acme' },
                    tags: ['enterprise'],
                    noteCount: 2,
                    relationships: { [RELATIONSHIP_ID]: [42] },
                    customProperties: {},
                    customPropertyHistory: {},
                },
            ],
            plan
        )

        expect(rows).toEqual([[{ id: 'account-id', name: 'Acme', external_id: 'acme-1' }, ['enterprise'], 2, [42]]])
    })
})
