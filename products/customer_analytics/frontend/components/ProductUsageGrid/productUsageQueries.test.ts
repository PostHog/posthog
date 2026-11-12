import { NodeKind, AccountsTableRelationshipOperator, type AccountsTableRow } from '~/queries/schema/schema-general'

import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import { productUsageCount, productUsageRows } from './productUsageData'
import { buildProductUsageAccountsQuery, buildProductUsageHogQLQuery } from './productUsageQueries'

const account: AccountsTableRow = {
    id: 'account-1',
    name: 'Example',
    externalId: 'org-1',
    accountFields: {},
    relationships: {},
    customProperties: {},
    customPropertyHistory: {},
}
describe('product usage book queries', () => {
    it('applies the role and assigned user together and starts from the first 200 accounts', () => {
        expect(
            buildProductUsageAccountsQuery({
                search: ' Example ',
                assignedTo: [5],
                assignmentStatus: 'all',
                relationshipId: 'role-1',
            })
        ).toMatchObject({
            kind: NodeKind.AccountsTableQuery,
            columns: [],
            limit: 200,
            offset: 0,
            filters: [
                { kind: 'search', query: 'Example' },
                {
                    kind: 'relationship',
                    definitionId: 'role-1',
                    operator: AccountsTableRelationshipOperator.Exact,
                    userIds: [5],
                },
            ],
        })
    })
    it('binds only filtered account IDs and group keys, including non-default group indexes', () => {
        expect(
            buildProductUsageHogQLQuery('SELECT * FROM events WHERE {filters}', [account], { date_from: '-30d' }, 2)
        ).toMatchObject({
            values: { account_ids: ['account-1'], account_external_ids: ['org-1'] },
            filters: { dateRange: { date_from: '-30d' }, properties: [{ key: '$group_2', value: ['org-1'] }] },
            tags: { name: 'customer_analytics_product_activity_hogql' },
        })
        expect(() =>
            buildProductUsageHogQLQuery(
                'SELECT * FROM events WHERE {filters}',
                [{ ...account, externalId: null }],
                {},
                0
            )
        ).toThrow('No filtered account is linked')
        expect(() => buildProductUsageHogQLQuery('SELECT * FROM events WHERE {filters}', [account], {}, null)).toThrow(
            'Choose an account group type'
        )
        expect(
            buildProductUsageHogQLQuery('SELECT id FROM system.accounts WHERE id IN {account_ids}', [account], {}, null)
                .values
        ).toEqual({ account_ids: ['account-1'], account_external_ids: ['org-1'] })
    })
    it('counts people once across selected products and limits expanded rows to used products', () => {
        const result = {
            ...BOOK_ACTIVITY_MATRIX_MOCK,
            rows: [{ key: 'a', label: 'Example', externalId: 'org' }],
            series: [
                { key: 'pa', label: 'Analytics' },
                { key: 'replay', label: 'Replay' },
            ],
            data: [
                { row: 'a', column: '2026-10-01', series: 'pa', users: 2 },
                { row: 'a', column: '2026-10-01', series: 'replay', users: 1 },
            ],
            combinations: [
                { row: 'a', column: '2026-10-01', mask: 1, users: 1 },
                { row: 'a', column: '2026-10-01', mask: 3, users: 1 },
            ],
        }
        expect(productUsageCount(result, 'a', '2026-10-01', ['pa', 'replay'])).toBe(2)
        expect(productUsageRows(result, ['replay'], 'users').map((row) => row.productKey)).toEqual([
            undefined,
            'replay',
        ])
        expect(productUsageRows(result, ['replay'], 'count')).toHaveLength(1)
    })
})
