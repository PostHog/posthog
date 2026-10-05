import { getColumnInsertText, getSidebarAddJoinSourceTableName, getSidebarPreviewQuery } from './QueryDatabase'

describe('QueryDatabase', () => {
    describe('getColumnInsertText', () => {
        test.each([
            ['a column inserts its name at the cursor', { type: 'column', columnName: 'id' }, 'id'],
            // A row can render as a column without carrying a name, as the notebook's dataframe
            // section did for a while. Escaping the missing name throws, and the throw escapes the
            // row's <a> handler before it can preventDefault, so the browser follows the placeholder
            // href and drops the user on the project home page.
            ['a column with no name inserts nothing', { type: 'column' }, null],
            ['a row that is not a column inserts nothing', { type: 'table', columnName: 'id' }, null],
            ['a row with no record inserts nothing', undefined, null],
            [
                'a property definition inserts its fully escaped HogQL expression',
                {
                    type: 'column',
                    columnName: 'properties.checkout.step',
                    hogqlExpression: 'properties."checkout.step"',
                },
                'properties."checkout.step"',
            ],
        ])('%s', (_name, record, expected) => {
            expect(getColumnInsertText(record)).toEqual(expected)
        })
    })

    describe('getSidebarAddJoinSourceTableName', () => {
        test.each([
            ['table rows keep add join in the table-specific menu', 'table', 'events', undefined, null],
            ['views expose add join with the view name', 'view', 'my_view', undefined, 'my_view'],
            [
                'managed views expose add join with the view name',
                'managed-view',
                'managed_view',
                undefined,
                'managed_view',
            ],
            [
                'endpoints expose add join with the underlying table name',
                'endpoint',
                'my endpoint',
                'my_endpoint_v3',
                'my_endpoint_v3',
            ],
            ['endpoints without a table name do not expose add join', 'endpoint', 'my endpoint', undefined, null],
            ['unknown row types do not expose add join', undefined, 'mystery', undefined, null],
        ])('%s', (_name, recordType, itemName, tableName, expected) => {
            expect(getSidebarAddJoinSourceTableName(recordType, itemName, tableName)).toEqual(expected)
        })
    })

    describe('getSidebarPreviewQuery', () => {
        test.each([
            [
                'tables query the same shape as views, so both open on the results tab',
                { type: 'table' },
                'events',
                'SELECT * FROM events LIMIT 100',
            ],
            [
                'a dotted table name quotes only the parts that need it',
                { type: 'table' },
                'my source.orders',
                'SELECT * FROM "my source".orders LIMIT 100',
            ],
            ['views query their own name', { type: 'view' }, 'my_view', 'SELECT * FROM my_view LIMIT 100'],
            [
                'managed views query their own name',
                { type: 'managed-view' },
                'managed_view',
                'SELECT * FROM managed_view LIMIT 100',
            ],
            [
                'endpoints query the underlying table',
                { type: 'endpoint', tableName: 'my_endpoint_v3' },
                'my endpoint',
                'SELECT * FROM my_endpoint_v3 LIMIT 100',
            ],
            ['columns have nothing to query', { type: 'column' }, 'id', null],
            ['rows with no record have nothing to query', undefined, 'mystery', null],
        ])('%s', (_name, record, itemName, expected) => {
            expect(getSidebarPreviewQuery(record, itemName)).toEqual(expected)
        })
    })
})
