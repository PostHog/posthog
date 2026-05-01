import { getSidebarAddJoinSourceTableName } from './QueryDatabase'

describe('QueryDatabase', () => {
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
