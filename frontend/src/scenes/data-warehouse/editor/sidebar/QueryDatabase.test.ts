import { getColumnInsertText, getSidebarAddJoinSourceTableName } from './QueryDatabase'

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
})
